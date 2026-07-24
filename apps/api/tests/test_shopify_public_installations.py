from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    Organization,
    ReportJob,
    ShopifyStoreInvitation,
    Workspace,
)
from catora_api.shopify.public_installations import (
    SHOPIFY_PUBLIC_CREDENTIAL_SCHEME,
    ShopifyPublicInstallationService,
    parse_public_credential_reference,
)
from catora_api.shopify.public_session import ShopifyPublicSession, ShopifyPublicTokenBundle


class EmptyScalars:
    def all(self) -> list[ReportJob]:
        return []


class ActivationSession:
    def __init__(self, invitation: ShopifyStoreInvitation) -> None:
        self.invitation = invitation
        self.added: list[object] = []
        self.commit_count = 0
        self.refresh_count = 0

    async def scalar(self, _statement: object) -> object:
        return self.invitation

    async def scalars(self, _statement: object) -> EmptyScalars:
        return EmptyScalars()

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if hasattr(value, "id") and getattr(value, "id") is None:
                setattr(value, "id", uuid.uuid4())

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _value: object) -> None:
        self.refresh_count += 1


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        shopify_public_enabled=True,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret="q" * 32,
        shopify_public_app_url="http://localhost:3001",
        shopify_public_required_scopes=["read_products"],
        shopify_public_credential_encryption_key=base64.urlsafe_b64encode(
            b"u" * 32
        ).decode(),
    )


def _invitation() -> ShopifyStoreInvitation:
    return ShopifyStoreInvitation(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        activated_workspace_id=None,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        activated_at=None,
        revoked_at=None,
    )


@pytest.mark.asyncio
async def test_activation_provisions_isolated_workspace_and_encrypts_credentials() -> None:
    invitation = _invitation()
    session = ActivationSession(invitation)
    shopify_session = ShopifyPublicSession(
        shop_domain=invitation.shop_domain,
        user_id="42",
        issued_at=datetime.now(UTC) - timedelta(seconds=10),
        not_before=datetime.now(UTC) - timedelta(seconds=10),
        expires_at=datetime.now(UTC) + timedelta(seconds=50),
        token_id="test-jti",
        session_id="test-session",
    )
    access_value = "a" * 32
    refresh_value = "r" * 32

    activation = await ShopifyPublicInstallationService(_settings()).activate(
        cast(Any, session),
        invitation=invitation,
        shopify_session=shopify_session,
        token_bundle=ShopifyPublicTokenBundle(
            access_token=access_value,
            refresh_token=refresh_value,
            granted_scopes=("read_products",),
            expires_in=3600,
            refresh_token_expires_in=7_776_000,
        ),
    )

    assert activation.created is True
    assert invitation.status == "activated"
    assert invitation.activated_workspace_id == activation.workspace_id
    assert session.commit_count == 1
    assert session.refresh_count == 1
    assert any(isinstance(item, Organization) for item in session.added)
    assert any(isinstance(item, Workspace) for item in session.added)
    assert isinstance(activation.catalog_source, CatalogSource)
    assert activation.catalog_source.credential_ref is not None
    assert activation.catalog_source.credential_ref.startswith(
        f"{SHOPIFY_PUBLIC_CREDENTIAL_SCHEME}:"
    )
    snapshot = activation.installation.input_snapshot
    assert snapshot["distribution"] == "public"
    assert snapshot["feature_tier"] == "demo"
    assert access_value not in str(snapshot)
    assert refresh_value not in str(snapshot)
    assert any(
        isinstance(item, AuditEvent)
        and item.event_type == "shopify.public_installation_created"
        for item in session.added
    )


def test_public_credential_reference_is_strict() -> None:
    installation_id = uuid.uuid4()
    reference = f"{SHOPIFY_PUBLIC_CREDENTIAL_SCHEME}:{installation_id}"
    assert parse_public_credential_reference(reference) == installation_id
    with pytest.raises(ValueError):
        parse_public_credential_reference(f"shopify-installation:{installation_id}")
