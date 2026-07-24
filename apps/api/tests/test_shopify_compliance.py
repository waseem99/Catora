from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models import ReportJob, ShopifyStoreInvitation, Workspace
from catora_api.main import app
from catora_api.shopify import compliance
from catora_api.shopify.compliance import (
    SHOPIFY_COMPLIANCE_DELIVERY_TYPE,
    ShopifyComplianceError,
    receive_shopify_compliance_webhook,
)

PUBLIC_SECRET = "p" * 32


class ComplianceSession:
    def __init__(
        self,
        *,
        invitation: ShopifyStoreInvitation | None,
        workspace: Workspace | None,
        existing: ReportJob | None = None,
    ) -> None:
        self.invitation = invitation
        self.workspace = workspace
        self.existing = existing
        self.added: list[object] = []
        self.commit_count = 0

    async def get(self, model: object, _identifier: object) -> object | None:
        if model is ReportJob:
            return self.existing
        if model is Workspace:
            return self.workspace
        return None

    async def scalar(self, _statement: object) -> ShopifyStoreInvitation | None:
        return self.invitation

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        shopify_public_enabled=True,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret=PUBLIC_SECRET,
    )


def _signature(body: bytes, secret: str = PUBLIC_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _invitation_and_workspace() -> tuple[ShopifyStoreInvitation, Workspace]:
    issuer_workspace_id = uuid.uuid4()
    target_workspace = Workspace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Prospect Store — Shopify Catalog",
        slug="shopify-catalog",
    )
    invitation = ShopifyStoreInvitation(
        id=uuid.uuid4(),
        workspace_id=issuer_workspace_id,
        activated_workspace_id=target_workspace.id,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status="activated",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        activated_at=datetime.now(UTC),
        revoked_at=None,
    )
    return invitation, target_workspace


@pytest.mark.asyncio
async def test_valid_unknown_shop_compliance_probe_is_acknowledged_without_storage() -> None:
    body = b'{"shop_id":123,"shop_domain":"unknown-store.myshopify.com"}'
    session = ComplianceSession(invitation=None, workspace=None)

    receipt = await receive_shopify_compliance_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="customers/data_request",
        shop_domain="unknown-store.myshopify.com",
        webhook_id="unknown-shop-probe",
        supplied_signature=_signature(body),
    )

    assert receipt.action == "no_customer_data_held"
    assert receipt.persisted is False
    assert receipt.duplicate is False
    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_invalid_compliance_hmac_returns_authentication_error() -> None:
    body = b'{"shop_id":123}'
    session = ComplianceSession(invitation=None, workspace=None)

    with pytest.raises(ShopifyComplianceError, match="signature"):
        await receive_shopify_compliance_webhook(
            cast(Any, session),
            settings=_settings(),
            body=body,
            topic="customers/redact",
            shop_domain="unknown-store.myshopify.com",
            webhook_id="invalid-signature",
            supplied_signature=_signature(body, "w" * 32),
        )

    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_customer_request_records_no_customer_data_without_payload() -> None:
    invitation, workspace = _invitation_and_workspace()
    session = ComplianceSession(invitation=invitation, workspace=workspace)
    body = b'{"customer":{"id":987654321},"orders_requested":[111,222]}'

    receipt = await receive_shopify_compliance_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="customers/data_request",
        shop_domain=invitation.shop_domain,
        webhook_id="customer-data-request",
        supplied_signature=_signature(body),
    )

    assert receipt.action == "no_customer_data_held"
    assert receipt.persisted is True
    delivery = next(item for item in session.added if isinstance(item, ReportJob))
    assert delivery.report_type == SHOPIFY_COMPLIANCE_DELIVERY_TYPE
    assert delivery.status == "completed"
    assert "customer" not in delivery.input_snapshot
    assert "orders_requested" not in delivery.input_snapshot
    assert body.decode() not in str(delivery.input_snapshot)
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_shop_redact_queues_isolated_workspace_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invitation, workspace = _invitation_and_workspace()
    session = ComplianceSession(invitation=invitation, workspace=workspace)
    body = b'{"shop_id":123,"shop_domain":"prospect-store.myshopify.com"}'
    queued: list[tuple[str, list[str]]] = []

    def send_task(name: str, args: list[str]) -> None:
        queued.append((name, args))

    monkeypatch.setattr(compliance.celery_app, "send_task", send_task)
    receipt = await receive_shopify_compliance_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="shop/redact",
        shop_domain=invitation.shop_domain,
        webhook_id="shop-redact-request",
        supplied_signature=_signature(body),
    )

    delivery = next(item for item in session.added if isinstance(item, ReportJob))
    assert receipt.action == "delete_shop_workspace"
    assert delivery.status == "queued"
    assert delivery.input_snapshot["target_workspace_id"] == str(workspace.id)
    assert delivery.input_snapshot["target_organization_id"] == str(
        workspace.organization_id
    )
    assert "shop_domain" not in delivery.input_snapshot
    assert queued == [("catora.shopify.compliance", [str(delivery.id)])]


def test_compliance_route_is_registered_without_payload_schema() -> None:
    route = "/api/v1/shopify/compliance"
    schema = app.openapi()
    assert route in schema["paths"]
    serialized = str(schema["paths"][route]).casefold()
    assert "customer_id" not in serialized
    assert "orders_requested" not in serialized
    assert "client_secret" not in serialized
