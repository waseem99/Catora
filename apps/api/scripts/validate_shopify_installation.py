from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from sqlalchemy import select

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import CatalogSource, ReportJob, User, Workspace
from catora_api.shopify.installations import (
    SHOPIFY_INSTALLATION_TYPE,
    ShopifyInstallationService,
)

SHOP = "northstar-living-demo.myshopify.com"
ACCESS_VALUE = "acceptance-access-credential"
REFRESH_VALUE = "acceptance-refresh-credential"


def signed_query(*, state: str, code: str, secret: str) -> list[tuple[str, str]]:
    unsigned = [
        ("code", code),
        ("shop", SHOP),
        ("state", state),
        ("timestamp", "1784779200"),
    ]
    message = urlencode(sorted(unsigned))
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return [*unsigned, ("hmac", digest)]


async def validate() -> None:
    settings = get_settings()

    async def token_exchange(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if "code" not in form:
            raise RuntimeError(
                "Acceptance flow expected an authorization-code exchange"
            )
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_VALUE,
                "scope": "read_products",
                "expires_in": 3600,
                "refresh_token": REFRESH_VALUE,
                "refresh_token_expires_in": 7_776_000,
            },
        )

    transport = httpx.MockTransport(token_exchange)
    async with httpx.AsyncClient(transport=transport) as client:
        service = ShopifyInstallationService(settings, client=client)
        async with SessionFactory() as session:
            workspace = await session.scalar(
                select(Workspace).where(Workspace.slug == "sales-demo")
            )
            user = await session.scalar(
                select(User).where(User.email == "demo@catora.local")
            )
            if workspace is None or user is None:
                raise RuntimeError("Run the enterprise demo seed first")

            authorization_url, state, _expires_at = await service.start(
                session,
                workspace_id=workspace.id,
                actor_user_id=user.id,
                shop_domain=SHOP,
            )
            query = parse_qs(urlparse(authorization_url).query)
            if query.get("scope") != ["read_products"]:
                raise RuntimeError("Authorization did not use the minimum scope")

            installation = await service.complete_callback(
                session,
                query_items=signed_query(
                    state=state,
                    code="acceptance-code",
                    secret=settings.shopify_client_secret,
                ),
                state_cookie=state,
            )
            snapshot = dict(installation.input_snapshot)
            serialized = json.dumps(snapshot, sort_keys=True)
            if ACCESS_VALUE in serialized or REFRESH_VALUE in serialized:
                raise RuntimeError("Shopify credential plaintext was persisted")
            if installation.status != "active":
                raise RuntimeError("Shopify installation did not become active")
            if snapshot.get("granted_scopes") != ["read_products"]:
                raise RuntimeError("Granted scopes were not persisted exactly")
            source_value = snapshot.get("catalog_source_id")
            if not isinstance(source_value, str):
                raise RuntimeError("Shopify catalog source identity was not persisted")
            source = await session.get(CatalogSource, uuid.UUID(source_value))
            if (
                source is None
                or source.credential_ref
                != f"shopify-installation:{installation.id}"
            ):
                raise RuntimeError(
                    "Shopify catalog source was not linked to the vault"
                )

            resolved = await ShopifyInstallationService(settings).resolve_access_token(
                installation.id
            )
            if resolved.get_secret_value() != ACCESS_VALUE:
                raise RuntimeError("Encrypted Shopify credential did not resolve")

            original_id = installation.id
            second_url, second_state, _ = await service.start(
                session,
                workspace_id=workspace.id,
                actor_user_id=user.id,
                shop_domain=SHOP,
            )
            if parse_qs(urlparse(second_url).query).get("state") != [second_state]:
                raise RuntimeError("Reconnect authorization state was not preserved")
            reconnected = await service.complete_callback(
                session,
                query_items=signed_query(
                    state=second_state,
                    code="reconnect-code",
                    secret=settings.shopify_client_secret,
                ),
                state_cookie=second_state,
            )
            if reconnected.id != original_id:
                raise RuntimeError("Reconnect duplicated the installation record")

            await service.disconnect(
                session,
                installation=reconnected,
                actor_user_id=user.id,
            )
            await session.refresh(reconnected)
            if reconnected.status != "disconnected":
                raise RuntimeError("Shopify installation did not disconnect")
            disconnected_snapshot = json.dumps(
                reconnected.input_snapshot,
                sort_keys=True,
            )
            if "v1." in disconnected_snapshot:
                raise RuntimeError(
                    "Disconnect retained encrypted credential material"
                )
            await session.refresh(source)
            if (
                source.credential_ref is not None
                or source.status != "disconnected"
            ):
                raise RuntimeError(
                    "Disconnect did not revoke the catalog source reference"
                )

            installation_count = len(
                list(
                    (
                        await session.scalars(
                            select(ReportJob).where(
                                ReportJob.workspace_id == workspace.id,
                                ReportJob.report_type == SHOPIFY_INSTALLATION_TYPE,
                            )
                        )
                    ).all()
                )
            )
            if installation_count != 1:
                raise RuntimeError(
                    "Reconnect created duplicate installation state"
                )

    print("Shopify installation lifecycle acceptance check passed.")


if __name__ == "__main__":
    asyncio.run(validate())
