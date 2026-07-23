from __future__ import annotations

import base64
import hashlib
import hmac

from catora_api.main import app
from catora_api.shopify.webhooks import (
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
