from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from catora_api.api.shopify_public import _installation_view
from catora_api.db.models import ReportJob, ShopifyStoreInvitation
from catora_api.main import app


def _invitation() -> ShopifyStoreInvitation:
    workspace_id = uuid.uuid4()
    return ShopifyStoreInvitation(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        activated_workspace_id=workspace_id,
        created_by_user_id=uuid.uuid4(),
        shop_domain="prospect-store.myshopify.com",
        prospect_name="Prospect Store",
        feature_tier="demo",
        status="activated",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        activated_at=datetime.now(UTC),
        revoked_at=None,
    )


def test_public_installation_view_exposes_bounded_catalog_status() -> None:
    invitation = _invitation()
    installation = ReportJob(
        id=uuid.uuid4(),
        workspace_id=invitation.activated_workspace_id,
        report_type="shopify_installation",
        status="active",
        input_snapshot={
            "distribution": "public",
            "shop_domain": invitation.shop_domain,
            "catalog_source_id": str(uuid.uuid4()),
            "sync_status": "completed",
            "product_count": 120,
            "variant_count": 240,
            "warning_count": 3,
            "assigned_category_count": 100,
            "ambiguous_category_count": 12,
            "unclassified_category_count": 8,
            "last_successful_sync_at": "2026-07-24T12:00:00+00:00",
            "last_sync_job_id": str(uuid.uuid4()),
            "last_audit_run_id": str(uuid.uuid4()),
            "encrypted_access_token": "must-not-appear",
            "encrypted_refresh_token": "must-not-appear",
        },
        template_version="shopify-public-installation-v1",
    )

    view = _installation_view(installation, invitation)

    assert view.shop_domain == invitation.shop_domain
    assert view.installation_status == "active"
    assert view.sync_status == "completed"
    assert view.product_count == 120
    assert view.variant_count == 240
    assert view.warning_count == 3
    assert view.assigned_category_count == 100
    assert view.ambiguous_category_count == 12
    assert view.unclassified_category_count == 8
    assert view.reauthorization_required is False
    serialized = view.model_dump_json()
    assert "encrypted_access_token" not in serialized
    assert "encrypted_refresh_token" not in serialized
    assert "must-not-appear" not in serialized


def test_public_installation_view_marks_reauthorization() -> None:
    invitation = _invitation()
    installation = ReportJob(
        id=uuid.uuid4(),
        workspace_id=invitation.activated_workspace_id,
        report_type="shopify_installation",
        status="refresh_required",
        input_snapshot={
            "distribution": "public",
            "shop_domain": invitation.shop_domain,
            "sync_status": "failed",
            "last_sync_error_type": "CredentialExpired",
        },
        template_version="shopify-public-installation-v1",
    )

    view = _installation_view(installation, invitation)

    assert view.installation_status == "refresh_required"
    assert view.sync_status == "failed"
    assert view.reauthorization_required is True
    assert view.last_sync_error_type == "CredentialExpired"


def test_embedded_status_and_sync_routes_never_expose_credentials() -> None:
    schema = app.openapi()
    for route in (
        "/api/v1/shopify/public/installation",
        "/api/v1/shopify/public/installation/sync",
    ):
        assert route in schema["paths"]
        serialized = str(schema["paths"][route]).casefold()
        assert "access_token" not in serialized
        assert "refresh_token" not in serialized
        assert "client_secret" not in serialized
