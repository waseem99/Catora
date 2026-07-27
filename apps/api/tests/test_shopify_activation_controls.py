from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException

from catora_api.api import shopify_public
from catora_api.config import Settings
from catora_api.db.models import ShopifyStoreInvitation
from catora_api.shopify.public_session import ShopifyPublicSession


def _settings(*, new_activations_enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        shopify_public_enabled=True,
        shopify_public_registration_identity="public_development",
        shopify_public_new_activations_enabled=new_activations_enabled,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret="q" * 32,
        shopify_public_app_url="http://localhost:3001",
        shopify_public_required_scopes=["read_products"],
        shopify_public_credential_encryption_key=base64.urlsafe_b64encode(
            b"u" * 32
        ).decode(),
    )


def _invitation(*, activated: bool) -> ShopifyStoreInvitation:
    workspace_id = uuid.uuid4() if activated else None
    return ShopifyStoreInvitation(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        activated_workspace_id=workspace_id,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status="activated" if activated else "pending",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        activated_at=datetime.now(UTC) if activated else None,
        revoked_at=None,
    )


def _shopify_session() -> ShopifyPublicSession:
    now = datetime.now(UTC)
    return ShopifyPublicSession(
        shop_domain="prospect-store.myshopify.com",
        user_id="42",
        issued_at=now - timedelta(seconds=10),
        not_before=now - timedelta(seconds=10),
        expires_at=now + timedelta(seconds=50),
        token_id="test-jti",
        session_id="test-session",
    )


class TokenExchangeMustNotRun:
    def __init__(self, _settings: Settings) -> None:
        pass

    async def exchange(self, **_kwargs: object) -> None:
        raise AssertionError("token exchange must not run while activation is paused")


@pytest.mark.asyncio
async def test_route_rejects_paused_first_activation_before_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invitation = _invitation(activated=False)
    monkeypatch.setattr(
        shopify_public,
        "_authenticated_shopify_session",
        lambda _request, _settings: ("session-token", _shopify_session()),
    )

    async def invitation_for_session(
        _session: object,
        _shopify_session: ShopifyPublicSession,
    ) -> ShopifyStoreInvitation:
        return invitation

    monkeypatch.setattr(shopify_public, "_invitation_for_session", invitation_for_session)
    monkeypatch.setattr(
        shopify_public,
        "ShopifyPublicTokenExchange",
        TokenExchangeMustNotRun,
    )

    with pytest.raises(HTTPException) as captured:
        await shopify_public.activate_shopify_public_installation(
            cast(Any, object()),
            cast(Any, object()),
            _settings(new_activations_enabled=False),
        )

    assert captured.value.status_code == 503
    assert "temporarily paused" in str(captured.value.detail)
