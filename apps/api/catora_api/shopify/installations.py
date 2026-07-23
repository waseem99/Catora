from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import Settings, get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import AuditEvent, CatalogSource, ReportJob
from catora_api.secrets import SecretValue
from catora_api.shopify.crypto import CredentialCipher, CredentialEncryptionError

SHOPIFY_INSTALLATION_TYPE = "shopify_installation"
SHOPIFY_OAUTH_STATE_TYPE = "shopify_oauth_state"
SHOPIFY_CREDENTIAL_SCHEME = "shopify-installation"
_SHOP_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


class ShopifyInstallationError(ValueError):
    pass


class ShopifyOAuthError(ShopifyInstallationError):
    pass


class ShopifyCredentialError(ShopifyInstallationError):
    pass


def normalize_shop_domain(value: str) -> str:
    normalized = value.strip().casefold()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    normalized = normalized.strip("/")
    if "/" in normalized or ":" in normalized or not _SHOP_PATTERN.fullmatch(normalized):
        raise ValueError("Shopify shop must use its permanent *.myshopify.com hostname")
    return normalized


def verify_shopify_query_hmac(
    items: Sequence[tuple[str, str]],
    *,
    client_secret: str,
) -> bool:
    supplied = next((value for key, value in items if key == "hmac"), "")
    if not supplied or len(supplied) != 64:
        return False
    filtered = [(key, value) for key, value in items if key != "hmac"]
    message = urlencode(sorted(filtered), doseq=True)
    digest = hmac.new(
        client_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, supplied)


def _now() -> datetime:
    return datetime.now(UTC)


def _text(snapshot: Mapping[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _uuid(snapshot: Mapping[str, object], key: str) -> uuid.UUID | None:
    value = _text(snapshot, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _datetime(snapshot: Mapping[str, object], key: str) -> datetime | None:
    value = _text(snapshot, key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _string_list(snapshot: Mapping[str, object], key: str) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def credential_reference(installation_id: uuid.UUID) -> str:
    return f"{SHOPIFY_CREDENTIAL_SCHEME}:{installation_id}"


def parse_credential_reference(reference: str) -> uuid.UUID:
    scheme, separator, value = reference.partition(":")
    if separator != ":" or scheme != SHOPIFY_CREDENTIAL_SCHEME:
        raise ShopifyCredentialError("Unsupported Shopify credential reference")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ShopifyCredentialError("Invalid Shopify credential reference") from exc


class ShopifyInstallationService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def _require_enabled(self) -> None:
        if not self.settings.shopify_enabled:
            raise ShopifyInstallationError("The Shopify pilot app is not configured")
        self.settings.validate_shopify()

    def _cipher(self) -> CredentialCipher:
        return CredentialCipher(self.settings.shopify_encryption_key_bytes())

    async def start(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        shop_domain: str,
    ) -> tuple[str, str, datetime]:
        self._require_enabled()
        shop = normalize_shop_domain(shop_domain)
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        expires_at = _now() + timedelta(
            minutes=self.settings.shopify_oauth_state_ttl_minutes
        )
        state_record = ReportJob(
            workspace_id=workspace_id,
            report_type=SHOPIFY_OAUTH_STATE_TYPE,
            status="pending",
            input_snapshot={
                "state_hash": state_hash,
                "shop_domain": shop,
                "workspace_id": str(workspace_id),
                "actor_user_id": str(actor_user_id),
                "expires_at": expires_at.isoformat(),
            },
            template_version="shopify-oauth-v1",
        )
        session.add(state_record)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="shopify.installation_started",
                entity_type="report_job",
                entity_id=state_record.id,
                payload={
                    "shop_domain": shop,
                    "required_scopes": list(self.settings.shopify_required_scopes),
                    "expires_at": expires_at.isoformat(),
                },
            )
        )
        await session.commit()
        authorization_url = self.authorization_url(shop=shop, state=state)
        return authorization_url, state, expires_at

    def authorization_url(self, *, shop: str, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.settings.shopify_client_id,
                "scope": ",".join(self.settings.shopify_required_scopes),
                "redirect_uri": self.settings.shopify_callback_url,
                "state": state,
            }
        )
        return f"https://{shop}/admin/oauth/authorize?{query}"

    async def complete_callback(
        self,
        session: AsyncSession,
        *,
        query_items: Sequence[tuple[str, str]],
        state_cookie: str | None,
    ) -> ReportJob:
        self._require_enabled()
        values = dict(query_items)
        state = values.get("state", "")
        code = values.get("code", "")
        shop = normalize_shop_domain(values.get("shop", ""))
        if not state or not code or not state_cookie:
            raise ShopifyOAuthError("Shopify authorization callback is incomplete")
        if not hmac.compare_digest(state, state_cookie):
            raise ShopifyOAuthError("Shopify authorization state does not match this browser")
        if not verify_shopify_query_hmac(
            query_items,
            client_secret=self.settings.shopify_client_secret,
        ):
            raise ShopifyOAuthError("Shopify authorization signature is invalid")

        state_hash = hashlib.sha256(state.encode()).hexdigest()
        pending_states = list(
            (
                await session.scalars(
                    select(ReportJob)
                    .where(
                        ReportJob.report_type == SHOPIFY_OAUTH_STATE_TYPE,
                        ReportJob.status == "pending",
                    )
                    .order_by(ReportJob.created_at.desc())
                    .limit(200)
                )
            ).all()
        )
        state_record = next(
            (
                item
                for item in pending_states
                if hmac.compare_digest(
                    _text(item.input_snapshot, "state_hash") or "",
                    state_hash,
                )
            ),
            None,
        )
        if state_record is None:
            raise ShopifyOAuthError("Shopify authorization state is invalid or already used")
        snapshot = dict(state_record.input_snapshot)
        if _text(snapshot, "shop_domain") != shop:
            raise ShopifyOAuthError("Shopify authorization shop does not match the request")
        expires_at = _datetime(snapshot, "expires_at")
        if expires_at is None or expires_at <= _now():
            state_record.status = "expired"
            await session.commit()
            raise ShopifyOAuthError("Shopify authorization state has expired")

        state_record.status = "exchanging"
        await session.commit()
        try:
            token = await self._exchange_code(shop=shop, code=code)
            installation = await self._persist_installation(
                session,
                state_record=state_record,
                shop=shop,
                token=token,
            )
            state_record.status = "consumed"
            state_record.input_snapshot = {
                **snapshot,
                "consumed_at": _now().isoformat(),
                "installation_id": str(installation.id),
            }
            await session.commit()
            return installation
        except Exception:
            await session.rollback()
            failed_state = await session.get(ReportJob, state_record.id)
            if failed_state is not None:
                failed_state.status = "failed"
                failed_state.input_snapshot = {
                    **dict(failed_state.input_snapshot),
                    "failed_at": _now().isoformat(),
                }
                await session.commit()
            raise

    async def _request_token(self, shop: str, data: Mapping[str, str]) -> dict[str, Any]:
        url = f"https://{shop}/admin/oauth/access_token"
        try:
            if self._client is not None:
                response = await self._client.post(
                    url,
                    data=dict(data),
                    headers={"Accept": "application/json"},
                    timeout=self.settings.shopify_http_timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.shopify_http_timeout_seconds
                ) as client:
                    response = await client.post(
                        url,
                        data=dict(data),
                        headers={"Accept": "application/json"},
                    )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ShopifyOAuthError("Shopify credential exchange failed") from exc
        if not isinstance(payload, dict):
            raise ShopifyOAuthError("Shopify credential response was invalid")
        return cast(dict[str, Any], payload)

    async def _exchange_code(self, *, shop: str, code: str) -> dict[str, Any]:
        data = {
            "client_id": self.settings.shopify_client_id,
            "client_secret": self.settings.shopify_client_secret,
            "code": code,
        }
        if self.settings.shopify_expiring_offline_tokens:
            data["expiring"] = "1"
        return await self._request_token(shop, data)

    async def _refresh_tokens(self, *, shop: str, refresh_token: str) -> dict[str, Any]:
        return await self._request_token(
            shop,
            {
                "client_id": self.settings.shopify_client_id,
                "client_secret": self.settings.shopify_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    def _validate_token_payload(self, payload: Mapping[str, Any]) -> tuple[str, list[str]]:
        access_token = payload.get("access_token")
        scope_value = payload.get("scope")
        if not isinstance(access_token, str) or not access_token:
            raise ShopifyOAuthError("Shopify credential response did not include a token")
        if not isinstance(scope_value, str):
            raise ShopifyOAuthError("Shopify credential response did not include scopes")
        scopes = sorted({scope.strip() for scope in scope_value.split(",") if scope.strip()})
        required = sorted(self.settings.shopify_required_scopes)
        if scopes != required:
            raise ShopifyOAuthError("Shopify granted scopes do not match Catora's minimum scope")
        return access_token, scopes

    async def _persist_installation(
        self,
        session: AsyncSession,
        *,
        state_record: ReportJob,
        shop: str,
        token: Mapping[str, Any],
    ) -> ReportJob:
        access_token, scopes = self._validate_token_payload(token)
        workspace_id = cast(uuid.UUID, state_record.workspace_id)
        actor_user_id = _uuid(state_record.input_snapshot, "actor_user_id")
        active_installations = list(
            (
                await session.scalars(
                    select(ReportJob).where(
                        ReportJob.report_type == SHOPIFY_INSTALLATION_TYPE,
                        ReportJob.status == "active",
                    )
                )
            ).all()
        )
        conflict = next(
            (
                item
                for item in active_installations
                if item.workspace_id != workspace_id
                and _text(item.input_snapshot, "shop_domain") == shop
            ),
            None,
        )
        if conflict is not None:
            raise ShopifyOAuthError(
                "This Shopify shop is already connected to another Catora workspace"
            )
        existing = await self.find_installation(
            session,
            workspace_id=workspace_id,
            shop_domain=shop,
        )
        installation = existing or ReportJob(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            report_type=SHOPIFY_INSTALLATION_TYPE,
            status="pending",
            input_snapshot={},
            template_version="shopify-installation-v1",
        )
        if existing is None:
            session.add(installation)
            await session.flush()

        now = _now()
        expires_in = token.get("expires_in")
        refresh_expires_in = token.get("refresh_token_expires_in")
        access_expires_at = (
            now + timedelta(seconds=expires_in)
            if isinstance(expires_in, int) and expires_in > 0
            else None
        )
        refresh_expires_at = (
            now + timedelta(seconds=refresh_expires_in)
            if isinstance(refresh_expires_in, int) and refresh_expires_in > 0
            else None
        )
        refresh_token = token.get("refresh_token")
        if self.settings.shopify_expiring_offline_tokens and not isinstance(
            refresh_token, str
        ):
            raise ShopifyOAuthError("Shopify did not provide the required refresh token")

        cipher = self._cipher()
        encrypted_access = cipher.encrypt(
            access_token,
            installation_id=str(installation.id),
            shop_domain=shop,
            purpose="access",
        ).value
        encrypted_refresh = (
            cipher.encrypt(
                refresh_token,
                installation_id=str(installation.id),
                shop_domain=shop,
                purpose="refresh",
            ).value
            if isinstance(refresh_token, str)
            else None
        )
        snapshot = dict(installation.input_snapshot)
        source_id = _uuid(snapshot, "catalog_source_id")
        source = await session.get(CatalogSource, source_id) if source_id else None
        if source is None:
            source = CatalogSource(
                workspace_id=workspace_id,
                name=f"{shop} Shopify catalog",
                source_type="shopify",
                status="ready",
                credential_ref=credential_reference(installation.id),
                config={
                    "shop_domain": shop,
                    "api_version": "2026-07",
                    "updated_after": None,
                    "normalization_aliases": {},
                },
            )
            session.add(source)
            await session.flush()
        else:
            source.status = "ready"
            source.credential_ref = credential_reference(installation.id)

        installation.status = "active"
        installation.input_snapshot = {
            "shop_domain": shop,
            "workspace_id": str(workspace_id),
            "catalog_source_id": str(source.id),
            "granted_scopes": scopes,
            "token_mode": (
                "expiring_offline"
                if self.settings.shopify_expiring_offline_tokens
                else "non_expiring_offline"
            ),
            "encrypted_access_token": encrypted_access,
            "encrypted_refresh_token": encrypted_refresh,
            "access_token_expires_at": (
                access_expires_at.isoformat() if access_expires_at else None
            ),
            "refresh_token_expires_at": (
                refresh_expires_at.isoformat() if refresh_expires_at else None
            ),
            "installed_at": snapshot.get("installed_at") or now.isoformat(),
            "refreshed_at": now.isoformat(),
            "disconnected_at": None,
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type=(
                    "shopify.reconnected" if existing is not None else "shopify.installed"
                ),
                entity_type="report_job",
                entity_id=installation.id,
                payload={
                    "shop_domain": shop,
                    "catalog_source_id": str(source.id),
                    "granted_scopes": scopes,
                    "token_mode": installation.input_snapshot["token_mode"],
                },
            )
        )
        await session.commit()
        await session.refresh(installation)
        return installation

    async def find_installation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        shop_domain: str | None = None,
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
        if shop_domain is None:
            return installations[0] if installations else None
        shop = normalize_shop_domain(shop_domain)
        return next(
            (
                installation
                for installation in installations
                if _text(installation.input_snapshot, "shop_domain") == shop
            ),
            None,
        )

    async def disconnect(
        self,
        session: AsyncSession,
        *,
        installation: ReportJob,
        actor_user_id: uuid.UUID,
    ) -> None:
        snapshot = dict(installation.input_snapshot)
        source_id = _uuid(snapshot, "catalog_source_id")
        source = await session.get(CatalogSource, source_id) if source_id else None
        if source is not None:
            source.status = "disconnected"
            source.credential_ref = None
        installation.status = "disconnected"
        installation.input_snapshot = {
            **snapshot,
            "encrypted_access_token": None,
            "encrypted_refresh_token": None,
            "access_token_expires_at": None,
            "refresh_token_expires_at": None,
            "disconnected_at": _now().isoformat(),
        }
        session.add(
            AuditEvent(
                workspace_id=installation.workspace_id,
                actor_user_id=actor_user_id,
                event_type="shopify.disconnected",
                entity_type="report_job",
                entity_id=installation.id,
                payload={
                    "shop_domain": _text(snapshot, "shop_domain"),
                    "catalog_source_id": str(source_id) if source_id else None,
                },
            )
        )
        await session.commit()

    async def resolve_access_token(self, installation_id: uuid.UUID) -> SecretValue:
        self._require_enabled()
        async with SessionFactory() as session:
            installation = await session.get(ReportJob, installation_id)
            if (
                installation is None
                or installation.report_type != SHOPIFY_INSTALLATION_TYPE
                or installation.status != "active"
            ):
                raise ShopifyCredentialError("Shopify installation is disconnected")
            snapshot = dict(installation.input_snapshot)
            shop = _text(snapshot, "shop_domain")
            encrypted_access = _text(snapshot, "encrypted_access_token")
            if shop is None or encrypted_access is None:
                installation.status = "disconnected"
                await session.commit()
                raise ShopifyCredentialError("Shopify credential is unavailable")

            access_expires_at = _datetime(snapshot, "access_token_expires_at")
            if access_expires_at is not None and access_expires_at <= _now() + timedelta(
                minutes=5
            ):
                await self._refresh_installation(session, installation)
                snapshot = dict(installation.input_snapshot)
                encrypted_access = _text(snapshot, "encrypted_access_token")
                if encrypted_access is None:
                    raise ShopifyCredentialError("Shopify credential refresh failed")
            try:
                access_token = self._cipher().decrypt(
                    encrypted_access,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="access",
                )
            except CredentialEncryptionError as exc:
                installation.status = "disconnected"
                installation.input_snapshot = {
                    **snapshot,
                    "encrypted_access_token": None,
                    "encrypted_refresh_token": None,
                    "failure_code": "CredentialDecryptionError",
                }
                await session.commit()
                raise ShopifyCredentialError("Shopify credential is unavailable") from exc
            return SecretValue(access_token)

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
            raise ShopifyCredentialError("Shopify reauthorization is required")
        try:
            refresh_token = self._cipher().decrypt(
                encrypted_refresh,
                installation_id=str(installation.id),
                shop_domain=shop,
                purpose="refresh",
            )
            payload = await self._refresh_tokens(
                shop=shop,
                refresh_token=refresh_token,
            )
            access_token, scopes = self._validate_token_payload(payload)
            new_refresh = payload.get("refresh_token")
            expires_in = payload.get("expires_in")
            refresh_expires_in = payload.get("refresh_token_expires_in")
            if not isinstance(new_refresh, str):
                raise ShopifyCredentialError("Shopify refresh token was not rotated")
            if not isinstance(expires_in, int) or not isinstance(
                refresh_expires_in, int
            ):
                raise ShopifyCredentialError("Shopify refresh expiry metadata is invalid")
            now = _now()
            cipher = self._cipher()
            installation.input_snapshot = {
                **snapshot,
                "granted_scopes": scopes,
                "encrypted_access_token": cipher.encrypt(
                    access_token,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="access",
                ).value,
                "encrypted_refresh_token": cipher.encrypt(
                    new_refresh,
                    installation_id=str(installation.id),
                    shop_domain=shop,
                    purpose="refresh",
                ).value,
                "access_token_expires_at": (
                    now + timedelta(seconds=expires_in)
                ).isoformat(),
                "refresh_token_expires_at": (
                    now + timedelta(seconds=refresh_expires_in)
                ).isoformat(),
                "refreshed_at": now.isoformat(),
            }
            installation.status = "active"
            session.add(
                AuditEvent(
                    workspace_id=installation.workspace_id,
                    actor_user_id=None,
                    event_type="shopify.credential_refreshed",
                    entity_type="report_job",
                    entity_id=installation.id,
                    payload={
                        "shop_domain": shop,
                        "granted_scopes": scopes,
                    },
                )
            )
            await session.commit()
        except (CredentialEncryptionError, ShopifyInstallationError) as exc:
            installation.status = "refresh_required"
            installation.input_snapshot = {
                **snapshot,
                "failure_code": type(exc).__name__,
            }
            await session.commit()
            raise ShopifyCredentialError("Shopify reauthorization is required") from exc
