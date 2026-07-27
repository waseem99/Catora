from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from catora_api.api.shopify_operations import _operator_view
from catora_api.db.models import ReportJob, ShopifyStoreInvitation
from catora_api.main import app


def _invitation(workspace_id: uuid.UUID) -> ShopifyStoreInvitation:
    now = datetime.now(UTC)
    return ShopifyStoreInvitation(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        activated_workspace_id=workspace_id,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status="activated",
        expires_at=now + timedelta(days=7),
        activated_at=now,
        revoked_at=None,
    )


def _installation(workspace_id: uuid.UUID) -> ReportJob:
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        report_type="shopify_installation",
        status="active",
        input_snapshot={
            "distribution": "public",
            "shop_domain": "prospect-store.myshopify.com",
            "catalog_source_id": str(uuid.uuid4()),
            "sync_status": "failed",
            "product_count": 1000,
            "variant_count": 2000,
            "sync_attempt_count": 4,
            "sync_retry_count": 3,
            "sync_next_retry_at": None,
            "sync_last_failure_at": "2026-07-27T05:20:00+00:00",
            "sync_last_failure_type": "TimeoutError",
            "sync_dead_lettered_at": "2026-07-27T05:20:00+00:00",
            "sync_recovery_required": True,
            "last_sync_error_type": "TimeoutError",
            "analysis_status": "completed",
            "analysis_finding_count": 12,
            "encrypted_access_token": "must-never-enter-view",
            "encrypted_refresh_token": "must-never-enter-view",
        },
        template_version="shopify-public-installation-v1",
    )


def _delivery(workspace_id: uuid.UUID, installation_id: uuid.UUID) -> ReportJob:
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        report_type="shopify_webhook_delivery",
        status="completed",
        input_snapshot={
            "installation_id": str(installation_id),
            "topic": "products/update",
            "received_at": "2026-07-27T05:19:00+00:00",
            "payload_sha256": "a" * 64,
            "webhook_id": "delivery-id-must-not-enter-view",
        },
        template_version="shopify-webhook-v3",
    )


def test_operator_view_exposes_recovery_state_without_credentials() -> None:
    workspace_id = uuid.uuid4()
    invitation = _invitation(workspace_id)
    installation = _installation(workspace_id)
    view = _operator_view(
        invitation,
        installation,
        _delivery(workspace_id, installation.id),
    )

    assert view.prospect_name == "Prospect Store"
    assert view.product_count == 1000
    assert view.variant_count == 2000
    assert view.sync_retry_count == 3
    assert view.sync_recovery_required is True
    assert view.sync_dead_lettered_at == datetime(
        2026,
        7,
        27,
        5,
        20,
        tzinfo=UTC,
    )
    assert view.last_webhook_topic == "products/update"
    assert view.last_webhook_received_at == datetime(
        2026,
        7,
        27,
        5,
        19,
        tzinfo=UTC,
    )
    serialized = json.dumps(view.model_dump(mode="json"))
    assert "encrypted_access_token" not in serialized
    assert "encrypted_refresh_token" not in serialized
    assert "must-never-enter-view" not in serialized
    assert "payload_sha256" not in serialized
    assert "webhook_id" not in serialized


def test_operator_list_and_recovery_routes_are_exposed() -> None:
    paths = set(app.openapi()["paths"])
    assert (
        "/api/v1/workspaces/{workspace_id}/shopify/public-installations" in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/shopify/public-installations/"
        "{installation_id}/recover"
        in paths
    )
