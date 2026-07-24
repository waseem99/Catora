from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from catora_api.db.models import AuditEvent, ShopifyStoreInvitation
from catora_api.main import app
from catora_api.shopify.invitations import (
    ShopifyInvitationError,
    ShopifyInvitationService,
)


class ScalarList:
    def __init__(self, values: list[ShopifyStoreInvitation]) -> None:
        self._values = values

    def all(self) -> list[ShopifyStoreInvitation]:
        return self._values


class InvitationSession:
    def __init__(
        self,
        *,
        scalar_values: list[ShopifyStoreInvitation | None] | None = None,
        scalars_values: list[list[ShopifyStoreInvitation]] | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.scalars_values = list(scalars_values or [])
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0
        self.refresh_count = 0

    async def scalar(self, _statement: object) -> ShopifyStoreInvitation | None:
        return self.scalar_values.pop(0)

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList(self.scalars_values.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _value: object) -> None:
        self.refresh_count += 1


def _invitation(
    *,
    status: str = "pending",
    expires_at: datetime | None = None,
    activated_workspace_id: uuid.UUID | None = None,
) -> ShopifyStoreInvitation:
    now = datetime.now(UTC)
    return ShopifyStoreInvitation(
        id=uuid.uuid4(),
        issuer_workspace_id=uuid.uuid4(),
        activated_workspace_id=activated_workspace_id,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status=status,
        expires_at=expires_at or now + timedelta(days=7),
        activated_at=now if status == "activated" else None,
        revoked_at=now if status == "revoked" else None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_invitation_normalizes_store_and_records_bounded_audit() -> None:
    issuer_workspace_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()
    session = InvitationSession(scalar_values=[None])

    invitation = await ShopifyInvitationService().create_or_replace(
        cast(Any, session),
        issuer_workspace_id=issuer_workspace_id,
        actor_user_id=actor_user_id,
        shop_domain="https://Prospect-Store.myshopify.com/",
        prospect_name=" Prospect Store ",
        expires_in_hours=168,
    )

    assert invitation.shop_domain == "prospect-store.myshopify.com"
    assert invitation.prospect_name == "Prospect Store"
    assert invitation.status == "pending"
    assert invitation.activated_workspace_id is None
    assert session.flush_count == 1
    assert session.commit_count == 1
    assert session.refresh_count == 1
    assert session.added[0] is invitation
    audit = cast(AuditEvent, session.added[1])
    assert audit.event_type == "shopify.public_invitation_created"
    assert audit.payload["shop_domain"] == "prospect-store.myshopify.com"
    assert "token" not in str(audit.payload).casefold()


@pytest.mark.asyncio
async def test_activated_store_cannot_be_reinvited_into_another_tenant() -> None:
    invitation = _invitation(status="activated", activated_workspace_id=uuid.uuid4())
    session = InvitationSession(scalar_values=[invitation])

    with pytest.raises(ShopifyInvitationError, match="cannot be replaced"):
        await ShopifyInvitationService().create_or_replace(
            cast(Any, session),
            issuer_workspace_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            shop_domain=invitation.shop_domain,
            prospect_name="Another tenant",
            expires_in_hours=24,
        )

    assert session.commit_count == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_expired_invitation_fails_closed_and_is_persisted() -> None:
    invitation = _invitation(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    session = InvitationSession(scalar_values=[invitation])

    with pytest.raises(ShopifyInvitationError, match="expired"):
        await ShopifyInvitationService().require_activatable(
            cast(Any, session),
            shop_domain=invitation.shop_domain,
        )

    assert invitation.status == "expired"
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_activation_is_store_bound_and_idempotent_for_the_same_workspace() -> None:
    target_workspace_id = uuid.uuid4()
    invitation = _invitation()
    session = InvitationSession(scalar_values=[invitation])

    activated = await ShopifyInvitationService().activate(
        cast(Any, session),
        shop_domain=invitation.shop_domain,
        activated_workspace_id=target_workspace_id,
    )

    assert activated.status == "activated"
    assert activated.activated_workspace_id == target_workspace_id
    assert activated.activated_at is not None
    assert session.commit_count == 1
    assert any(
        isinstance(item, AuditEvent)
        and item.event_type == "shopify.public_invitation_activated"
        for item in session.added
    )

    idempotent_session = InvitationSession(scalar_values=[activated])
    same = await ShopifyInvitationService().activate(
        cast(Any, idempotent_session),
        shop_domain=invitation.shop_domain,
        activated_workspace_id=target_workspace_id,
    )
    assert same is activated
    assert idempotent_session.commit_count == 0

    conflict_session = InvitationSession(scalar_values=[activated])
    with pytest.raises(ShopifyInvitationError, match="another Catora workspace"):
        await ShopifyInvitationService().activate(
            cast(Any, conflict_session),
            shop_domain=invitation.shop_domain,
            activated_workspace_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_invitation_listing_is_scoped_to_the_issuer_workspace_query() -> None:
    first = _invitation()
    second = _invitation(status="revoked")
    session = InvitationSession(scalars_values=[[first, second]])

    result = await ShopifyInvitationService().list_for_workspace(
        cast(Any, session),
        issuer_workspace_id=first.issuer_workspace_id,
    )

    assert result == (first, second)


def test_public_invitation_routes_never_expose_credentials() -> None:
    schema = app.openapi()
    paths = set(schema["paths"])
    collection = "/api/v1/workspaces/{workspace_id}/shopify/public-invitations"
    item = collection + "/{invitation_id}"
    assert collection in paths
    assert item in paths
    serialized = str(schema).casefold()
    assert "shopify_client_secret" not in serialized
    assert "access_token" not in str(schema["paths"][collection]).casefold()
    assert "refresh_token" not in str(schema["paths"][collection]).casefold()
