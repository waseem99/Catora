from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from catora_api.api.shopify_activity import delivery_view
from catora_api.db.models import ReportJob
from catora_api.main import app
from catora_api.shopify.webhooks import (
    SHOPIFY_WEBHOOK_DELIVERY_TYPE,
    SUPPORTED_TOPICS,
    verify_shopify_webhook_hmac,
)


def _signature(body: bytes, secret: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_shopify_webhook_hmac_uses_raw_body() -> None:
    body = b'{"id":123,"title":"Northstar Sofa"}'
    secret = "runtime-generated-test-secret"
    signature = _signature(body, secret)
    assert verify_shopify_webhook_hmac(body, signature, client_secret=secret)
    assert not verify_shopify_webhook_hmac(
        body + b" ",
        signature,
        client_secret=secret,
    )


def test_shopify_webhook_topics_are_read_only_catalog_lifecycle() -> None:
    assert {
        "app/uninstalled",
        "products/create",
        "products/update",
        "products/delete",
    } == SUPPORTED_TOPICS


def test_shopify_webhook_and_manual_sync_routes_are_exposed() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/v1/shopify/webhooks" in paths
    assert "/api/v1/workspaces/{workspace_id}/shopify/installation/sync" in paths
    assert "/api/v1/workspaces/{workspace_id}/shopify/webhooks/latest" in paths


def test_verified_delivery_view_excludes_raw_payload_and_signature() -> None:
    delivery = ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type=SHOPIFY_WEBHOOK_DELIVERY_TYPE,
        status="completed",
        input_snapshot={
            "topic": "products/update",
            "received_at": "2026-07-23T08:30:00+00:00",
            "processed_at": "2026-07-23T08:30:02+00:00",
            "product_id": "1234567890",
            "ingestion_job_id": str(uuid.uuid4()),
            "payload_sha256": "a" * 64,
        },
        template_version="shopify-webhook-v1",
    )

    view = delivery_view(delivery)

    assert view.topic == "products/update"
    assert view.status == "completed"
    assert view.signature_verified is True
    assert view.product_id == "1234567890"
    assert "payload_sha256" not in view.model_dump()
    assert "signature" not in view.model_dump()
