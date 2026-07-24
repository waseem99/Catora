from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings, get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    Locale,
    Market,
    Organization,
    ReportJob,
    ShopifyStoreInvitation,
    Storefront,
    Workspace,
)
from catora_api.secrets import SecretValue
from catora_api.shopify.crypto import CredentialCipher, CredentialEncryptionError
from catora_api.shopify.installations import SHOPIFY_INSTALLATION_TYPE, normalize_shop_domain
from catora_api.shopify.public_session import ShopifyPublicSession, ShopifyPublicTokenBundle

SHOPIFY_PUBLIC_CREDENTIAL_SCHEME = "shopify-public-installation"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class ShopifyPublicInstallationError(ValueError):
    pass


class ShopifyPublicCredentialError(ShopifyPublicInstallationError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyPublicActivation:
    installation: ReportJob
    catalog_source: CatalogSource
    workspace_id: uuid.UUID
    feature_tier: str
    created: bool


def public_credential_reference(installation_id: uuid.UUID) -> str:
    return f"{SHOPIFY_PUBLIC_CREDENTIAL_SCHEME}:{installation_id}"


def parse_public_credential_reference(reference: str) -> uuid.UUID:
    scheme, separator, value = reference.partition(":")
    if separator != ":" or scheme != SHOPIFY_PUBLIC_CREDENTIAL_SCHEME:
        raise ShopifyPublicCredentialError("Unsupported Shopify public credential reference")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ShopifyPublicCredentialError(
            "Invalid Shopify public credential reference"
        ) from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _text(snapshot: Mapping[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _datetime(snapshot: Mapping[str, object], key: str) -> datetime | None:
    value = _text(snapshot, key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.casefold()).strip("-")
    return normalized[:55] or "shopify-store"


class ShopifyPublicInstallationService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def _cipher(self) -> CredentialCipher:
        return CredentialCipher(self.settings.shopify_public_encryption_key_bytes())

    async def activate(
        self,
        session: AsyncSession,
        *,
        invitation: ShopifyStoreInvitation,
        shopify_session: ShopifyPublicSession,
        token_bundle: ShopifyPublicTokenBundle,
    ) -> ShopifyPublicActivation:
        self.settings.validate_shopify_public()
        shop = normalize_shop_domain(shopify_session.shop_domain)
        locked = await session.scalar(
            select(ShopifyStoreInvitation)
            .where(ShopifyStoreInvitation.id == invitation.id)
            .with_for_update()
        )
        if locked is None or locked.shop_domain != shop:
            raise ShopifyPublicInstallationError(
                "The Shopify store invitation is no longer available"
            )
        if locked.status == "pending" and locked.expires_at <= _now():
            locked.status = "expired"
            await session.commit()
            raise ShopifyPublicInstallationError(
                "The Shopify store invitation has expired"
            )
        if locked.status not in {"pending", "activated"}:
            raise ShopifyPublicInstallationError(
                "The Shopify store invitation is not active"
            )

        workspace_id = locked.activated_workspace_id
        created = workspace_id is None
        storefront: Storefront | None = None
        if workspace_id is None:
            organization = Organization(
                name=locked.prospect_name,
                slug=f"shopify-{_slug(locked.prospect_name)}-{locked.id.hex[:8]}",
            )
            session.add(organization)
            await session.flush()
            workspace = Workspace(
                organization_id=organization.id,
                name=f"{locked.prospect_name} — Shopify Catalog",
                slug="shopify-catalog",
            )
            session.add(workspace)
            await session.flush()
            workspace_id = cast(uuid.UUID, workspace.id)
            locale = Locale(
                workspace_id=workspace_id,
                code="en-US",
                language="en",
                region="US",
            )
            session.add(locale)
            await session.flush()
            storefront = Storefront(
                workspace_id=workspace_id,
                name=locked.prospect_name,
                domain=shop,
                platform="shopify",
                external_id=shop,
            )
            session.add(storefront)
            await session.flush()
            session.add(
                Market(
                    workspace_id=workspace_id,
                    storefront_id=storefront.id,
                    locale_id=locale.id,
                    code="US",
                    currency="USD",
                    name="Primary Shopify market",
                )
            )
        else:
            storefront = await session.scalar(
                select(Storefront).where(
                    Storefront.workspace_id == workspace_id,
                    Storefront.domain == shop,
                )
            )
            if storefront is None:
                storefront = Storefront(
                    workspace_id=workspace_id,
                    name=locked.prospect_name,
                    domain=shop,
                    platform="shopify",
                    external_id=shop,
                )
                session.add(storefront)
                await session.flush()

        installation = await self.find_installation(
            session,
            workspace_id=workspace_id,
            shop_domain=shop,
        )
        if installation is None:
            installation = ReportJob(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                report_type=SHOPIFY_INSTALLATION_TYPE,
                status="pending",
                input_snapshot={},
                template_version="shopify-public-installation-v1",
            )
            session.add(installation)
            await session.flush()

        snapshot = dict(installation.input_snapshot)
        source_id_text = _text(snapshot, "catalog_source_id")
        source: CatalogSource | None = None
        if source_id_text is not None:
            try:
                source = await session.get(CatalogSource, uuid.UUID(source_id_text))
            except ValueError:
                source = None
        if source is None:
            source = CatalogSource(
                workspace_id=workspace_id,
                storefront_id=storefront.id,
                name=f"{shop} Shopify catalog",
                source_type="shopify",
                status="ready",
                credential_ref=public_credential_reference(installation.id),
                config={
                    "shop_domain": shop,
                    "api_version": "2026-07",
                    "updated_after": None,
                    "normalization_aliases": {},
                    "distribution": "public",
                },
            )
            session.add(source)
            await session.flush()
        else:
            source.storefront_id = storefront.id
            source.status = "ready"
            source.credential_ref = public_credential_reference(installation.id)
            source.config = {
                **dict(source.config),
                "shop_domain": shop,
                "api_version": "2026-07",
                "distribution": "public",
            }

        now = _now()
        cipher = self._cipher()
        installation.status = "active"
        installation.input_snapshot = {
            **snapshot,
            "distribution": "public",
            "shop_domain": shop,
            "workspace_id": str(workspace_id),
            "catalog_source_id": str(source.id),
            "shopify_user_id": shopify_session.user_id,
            "feature_tier": locked.feature_tier,
            "granted_scopes": list(token_bundle.granted_scopes),
            "token_mode": "expiring_offline",
            "encrypted_access_token": cipher.encrypt(
                token_bundle.access_token,
                installation_id=str(installation.id),
                shop_domain=shop,
                purpose="access",
            ).value,
            "encrypted_refresh_token": cipher.encrypt(
                token_bundle.refresh_token,
                installation_id=str(installation.id),
                shop_domain=shop,
                purpose="refresh",
            ).value,
            "access_token_expires_at": (
                now + timedelta(seconds=token_bundle.expires_in)
            ).isoformat(),
            "refresh_token_expires_at": (
                now + timedelta(seconds=token_bundle.refresh_token_expires_in)
            ).isoformat(),
            "installed_at": snapshot.get("installed_at") or now.isoformat(),
            "refreshed_at": now.isoformat(),
            "disconnected_at": None,
            "sync_status": snapshot.get("sync_status") or "not_started",
        }
        locked.status = "activated"
        locked.activated_workspace_id = workspace_id
        locked.activated_at = locked.activated_at or now
        locked.revoked_at = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=None,
                event_type=(
                    "shopify.public_installation_created"
                    if created
                    else "shopify.public_installation_reauthorized"
                ),
                entity_type="report_job",
                entity_id=installation.id,
                payload={
                    "shop_domain": shop,
                    "catalog_source_id": str(source.id),
                    "invitation_id": str(locked.id),
                    "feature_tier": locked.feature_tier,
                    "granted_scopes": list(token_bundle.granted_scopes),
                },
            )
        )
        await session.commit()
        await session.refresh(installation)
        return ShopifyPublicActivation(
            installation=installation,
            catalog_source=source,
            workspace_id=workspace_id,
            feature_tier=locked.feature_tier,
            created=created,
        )

    async def find_installation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        shop_domain: str,
    ) -> ReportJob | None:
        installations = list(
            (
                await session.scalars(
                    select(ReportJob)
                    .where(
                        ReportJob.workspace_id == workspace_id,
                        ReportJob.report_type == SHOPIFY_INSTALLATION_TYPE,
                    )
                    .order_by(ReportJob.created_at.desc())
                    .limit(50)
                )
            ).all()
        )
        return next(
            (
                item
                for item in installations
                if item.input_snapshot.get("distribution") == "public"
                and item.input_snapshot.get("shop_domain") == shop_domain
            ),
            None,
        )

    async def resolve_access_token(self, installation_id: uuid.UUID) -> SecretValue:
        self.settings.validate_shopify_public()
        async with SessionFactory() as session:
            installation = await session.get(ReportJob, installation_id)
            if (
                installation is None
                or installation.report_type != SHOPIFY_INSTALLATION_TYPE
                or installation.status != "active"
                or installation.input_snapshot.get("distribution") != "public"
            ):
                raise ShopifyPublicCredentialError(
                    "Shopify public installation is disconnected"
                )
            snapshot = dict(installation.input_snapshot)
            shop = _text(snapshot, "shop_domain")
            encrypted_access = _text(snapshot, "encrypted_access_token")
            if shop is None or encrypted_access is None:
                installation.status = "disconnected"
                await session.commit()
                raise ShopifyPublicCredentialError(
                    "Shopify public credential is unavailable"
                )

            expires_at = _datetime(snapshot, "access_token_expires_at")
            if expires_at is not None and expires_at <= _now() + timedelta(minutes=5):
                await self._refresh_installation(session, installation)
                snapshot = dict(installation.input_snapshot)
                encrypted_access = _text(snapshot, "encrypted_access_token")
                if encrypted_access is None:
                    raise ShopifyPublicCredentialError(
                        "Shopify public credential refresh failed"
                    )
            try:
                value = self._cipher().decrypt(
                    encrypted_access,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="access",
                )
            except CredentialEncryptionError as exc:
                installation.status = "disconnected"
                await session.commit()
                raise ShopifyPublicCredentialError(
                    "Shopify public credential is unavailable"
                ) from exc
            return SecretValue(value)

    async def _refresh_installation(
        self,
        session: AsyncSession,
        installation: ReportJob,
    ) -> None:
        snapshot = dict(installation.input_snapshot)
        shop = _text(snapshot, "shop_domain")
        encrypted_refresh = _text(snapshot, "encrypted_refresh_token")
        refresh_expires_at = _datetime(snapshot, "refresh_token_expires_at")
        if (
            shop is None
            or encrypted_refresh is None
            or refresh_expires_at is None
            or refresh_expires_at <= _now()
        ):
            installation.status = "refresh_required"
            await session.commit()
            raise ShopifyPublicCredentialError(
                "Shopify public app reauthorization is required"
            )
        try:
            refresh_token = self._cipher().decrypt(
                encrypted_refresh,
                installation_id=str(installation.id),
                shop_domain=shop,
                purpose="refresh",
            )
            bundle = await self._request_refresh(shop=shop, refresh_token=refresh_token)
            now = _now()
            cipher = self._cipher()
            installation.input_snapshot = {
                **snapshot,
                "granted_scopes": list(bundle.granted_scopes),
                "encrypted_access_token": cipher.encrypt(
                    bundle.access_token,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="access",
                ).value,
                "encrypted_refresh_token": cipher.encrypt(
                    bundle.refresh_token,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="refresh",
                ).value,
                "access_token_expires_at": (
                    now + timedelta(seconds=bundle.expires_in)
                ).isoformat(),
                "refresh_token_expires_at": (
                    now + timedelta(seconds=bundle.refresh_token_expires_in)
                ).isoformat(),
                "refreshed_at": now.isoformat(),
            }
            installation.status = "active"
            session.add(
                AuditEvent(
                    workspace_id=installation.workspace_id,
                    actor_user_id=None,
                    event_type="shopify.public_credential_refreshed",
                    entity_type="report_job",
                    entity_id=installation.id,
                    payload={
                        "shop_domain": shop,
                        "granted_scopes": list(bundle.granted_scopes),
                    },
                )
            )
            await session.commit()
        except (CredentialEncryptionError, ShopifyPublicInstallationError) as exc:
            installation.status = "refresh_required"
            await session.commit()
            raise ShopifyPublicCredentialError(
                "Shopify public app reauthorization is required"
            ) from exc

    async def _request_refresh(
        self,
        *,
        shop: str,
        refresh_token: str,
    ) -> ShopifyPublicTokenBundle:
        endpoint = f"https://{shop}/admin/oauth/access_token"
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.shopify_public_http_timeout_seconds
        )
        try:
            response = await client.post(
                endpoint,
                data={
                    "client_id": self.settings.shopify_public_client_id,
                    "client_secret": self.settings.shopify_public_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ShopifyPublicInstallationError(
                "Shopify public credential refresh failed"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise ShopifyPublicInstallationError(
                "Shopify public credential refresh returned an invalid response"
            )
        return self._token_bundle(cast(dict[str, Any], payload))

    def _token_bundle(self, payload: Mapping[str, Any]) -> ShopifyPublicTokenBundle:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        refresh_expires_in = payload.get("refresh_token_expires_in")
        scope_value = payload.get("scope")
        if not isinstance(access_token, str) or not access_token:
            raise ShopifyPublicInstallationError(
                "Shopify public credential refresh did not return an access token"
            )
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ShopifyPublicInstallationError(
                "Shopify public credential refresh did not rotate the refresh token"
            )
        if (
            not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise ShopifyPublicInstallationError(
                "Shopify public access-token expiry is invalid"
            )
        if (
            not isinstance(refresh_expires_in, int)
            or isinstance(refresh_expires_in, bool)
            or refresh_expires_in <= 0
        ):
            raise ShopifyPublicInstallationError(
                "Shopify public refresh-token expiry is invalid"
            )
        if not isinstance(scope_value, str):
            raise ShopifyPublicInstallationError(
                "Shopify public credential refresh did not return scopes"
            )
        scopes = tuple(
            sorted({scope.strip() for scope in scope_value.split(",") if scope.strip()})
        )
        required = tuple(sorted(self.settings.shopify_public_required_scopes))
        if scopes != required:
            raise ShopifyPublicInstallationError(
                "Shopify public credential scopes no longer match read_products"
            )
        return ShopifyPublicTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scopes=scopes,
            expires_in=expires_in,
            refresh_token_expires_in=refresh_expires_in,
        )
