from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any, cast

import pytest

from catora_api.api import shopify as shopify_api
from catora_api.config import Settings
from catora_api.db.models import ReportJob
from catora_api.shopify import webhooks
from catora_api.shopify.webhooks import (
    ShopifyWebhookError,
    ShopifyWebhookReceipt,
    receive_shopify_webhook,
)


class ScalarList:
    def __init__(self, values: list[ReportJob]) -> None:
        self.values = values

    def all(self) -> list[ReportJob]:
        return self.values


class WebhookSession:
    def __init__(self, installations: list[ReportJob]) -> None:
        self.installations = installations
        self.added: list[object] = []
        self.commit_count = 0

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList(self.installations)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


class RequestStub:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = {
            "x-shopify-topic": "products/update",
            "x-shopify-shop-domain": "prospect-store.myshopify.com",
            "x-shopify-webhook-id": "public-only-delivery",
            "x-shopify-hmac-sha256": "signed",
        }

    async def body(self) -> bytes:
        return self._body


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _settings(*, same_secret: bool = False) -> Settings:
    custom_secret = "c" * 32
    public_secret = custom_secret if same_secret else "p" * 32
    return Settings(
        _env_file=None,
        shopify_enabled=True,
        shopify_client_id="custom-client-123456",
        shopify_client_secret=custom_secret,
        shopify_public_enabled=True,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret=public_secret,
    )


def _installation(*, distribution: str) -> ReportJob:
    snapshot: dict[str, object] = {
        "shop_domain": "prospect-store.myshopify.com",
        "catalog_source_id": str(uuid.uuid4()),
    }
    if distribution == "public":
        snapshot["distribution"] = "public"
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status="active",
        input_snapshot=snapshot,
        template_version="shopify-installation-v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("distribution", "secret"),
    [("custom", "c" * 32), ("public", "p" * 32)],
)
async def test_webhook_binds_signature_to_matching_installation_identity(
    monkeypatch: pytest.MonkeyPatch,
    distribution: str,
    secret: str,
) -> None:
    body = b'{"id":123}'
    session = WebhookSession([_installation(distribution=distribution)])
    queued: list[tuple[str, list[str]]] = []

    def send_task(name: str, args: list[str]) -> None:
        queued.append((name, args))

    monkeypatch.setattr(webhooks.celery_app, "send_task", send_task)
    receipt = await receive_shopify_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="products/update",
        shop_domain="prospect-store.myshopify.com",
        webhook_id=f"delivery-{distribution}",
        event_id=None,
        triggered_at=None,
        supplied_signature=_signature(body, secret),
    )

    assert receipt.distribution == distribution
    assert receipt.duplicate is False
    delivery = cast(ReportJob, session.added[0])
    assert delivery.input_snapshot["distribution"] == distribution
    assert delivery.input_snapshot["installation_id"] == str(session.installations[0].id)
    assert session.commit_count == 1
    assert queued == [("catora.shopify.webhook", [str(delivery.id)])]


@pytest.mark.asyncio
async def test_bulk_finish_webhook_persists_only_bounded_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "admin_graphql_api_id": "gid://shopify/BulkOperation/9001",
        "status": "completed",
        "type": "query",
        "completed_at": "2026-07-24T14:00:00Z",
        "error_code": None,
        "url": "https://signed-storage.example.test/secret-result.jsonl",
        "partial_data_url": "https://signed-storage.example.test/partial.jsonl",
    }
    body = json.dumps(payload).encode()
    session = WebhookSession([_installation(distribution="public")])
    monkeypatch.setattr(webhooks.celery_app, "send_task", lambda *_args, **_kwargs: None)

    await receive_shopify_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="bulk_operations/finish",
        shop_domain="prospect-store.myshopify.com",
        webhook_id="bulk-finish-delivery",
        event_id=None,
        triggered_at="2026-07-24T14:00:01Z",
        supplied_signature=_signature(body, "p" * 32),
    )

    delivery = cast(ReportJob, session.added[0])
    snapshot = dict(delivery.input_snapshot)
    assert snapshot["bulk_operation_id"] == "gid://shopify/BulkOperation/9001"
    assert snapshot["bulk_status"] == "completed"
    assert snapshot["bulk_type"] == "query"
    assert snapshot["bulk_completed_at"] == "2026-07-24T14:00:00Z"
    serialized = json.dumps(snapshot)
    assert "signed-storage" not in serialized
    assert "partial_data_url" not in serialized
    assert "url" not in snapshot


@pytest.mark.asyncio
async def test_public_signature_cannot_target_custom_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"id":123}'
    session = WebhookSession([_installation(distribution="custom")])
    monkeypatch.setattr(webhooks.celery_app, "send_task", lambda *_args, **_kwargs: None)

    with pytest.raises(ShopifyWebhookError, match="not active"):
        await receive_shopify_webhook(
            cast(Any, session),
            settings=_settings(),
            body=body,
            topic="products/update",
            shop_domain="prospect-store.myshopify.com",
            webhook_id="delivery-mismatch",
            event_id=None,
            triggered_at=None,
            supplied_signature=_signature(body, "p" * 32),
        )

    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_shared_app_secrets_fail_closed_as_ambiguous() -> None:
    body = b'{"id":123}'
    session = WebhookSession([_installation(distribution="public")])
    settings = _settings(same_secret=True)

    with pytest.raises(ShopifyWebhookError, match="ambiguous"):
        await receive_shopify_webhook(
            cast(Any, session),
            settings=settings,
            body=body,
            topic="products/update",
            shop_domain="prospect-store.myshopify.com",
            webhook_id="delivery-ambiguous",
            event_id=None,
            triggered_at=None,
            supplied_signature=_signature(body, settings.shopify_client_secret),
        )

    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_receiver_accepts_public_only_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id = uuid.uuid4()
    called = False

    async def receive(*_args: object, **_kwargs: object) -> ShopifyWebhookReceipt:
        nonlocal called
        called = True
        return ShopifyWebhookReceipt(
            delivery_id=delivery_id,
            duplicate=False,
            distribution="public",
        )

    monkeypatch.setattr(shopify_api, "receive_shopify_webhook", receive)
    response = await shopify_api.accept_shopify_webhook(
        cast(Any, RequestStub(b'{"id":123}')),
        cast(Any, object()),
        Settings(
            _env_file=None,
            shopify_enabled=False,
            shopify_public_enabled=True,
            shopify_public_client_id="public-client-123456",
            shopify_public_client_secret="p" * 32,
        ),
    )

    assert called is True
    assert response.delivery_id == delivery_id
    assert response.duplicate is False
