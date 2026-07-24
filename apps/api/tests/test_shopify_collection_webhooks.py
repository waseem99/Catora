from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models import ReportJob
from catora_api.shopify import webhooks
from catora_api.shopify.webhooks import receive_shopify_webhook


class ScalarList:
    def __init__(self, values: list[ReportJob]) -> None:
        self.values = values

    def all(self) -> list[ReportJob]:
        return self.values


class WebhookSession:
    def __init__(self, installation: ReportJob) -> None:
        self.installation = installation
        self.added: list[object] = []
        self.commit_count = 0

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList([self.installation])

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        shopify_enabled=False,
        shopify_public_enabled=True,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret="p" * 32,
    )


def _installation() -> ReportJob:
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status="active",
        input_snapshot={
            "shop_domain": "prospect-store.myshopify.com",
            "distribution": "public",
            "catalog_source_id": str(uuid.uuid4()),
        },
        template_version="shopify-installation-v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic",
    [
        "collections/create",
        "collections/update",
        "collections/delete",
    ],
)
async def test_collection_webhook_persists_only_bounded_collection_metadata(
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
) -> None:
    payload = {
        "id": 987654321,
        "title": "Wholesale",
        "admin_graphql_api_id": "gid://shopify/Collection/987654321",
        "products_count": 5000,
        "body_html": "sensitive merchant content",
    }
    body = json.dumps(payload).encode()
    session = WebhookSession(_installation())
    queued: list[tuple[str, list[str]]] = []

    def send_task(name: str, args: list[str]) -> None:
        queued.append((name, args))

    monkeypatch.setattr(webhooks.celery_app, "send_task", send_task)

    await receive_shopify_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic=topic,
        shop_domain="prospect-store.myshopify.com",
        webhook_id=f"collection-{topic}",
        event_id=None,
        triggered_at="2026-07-24T15:00:00Z",
        supplied_signature=_signature(body, "p" * 32),
    )

    delivery = cast(ReportJob, session.added[0])
    snapshot = dict(delivery.input_snapshot)
    assert snapshot["topic"] == topic
    assert snapshot["collection_id"] == "987654321"
    assert "product_id" not in snapshot
    serialized = json.dumps(snapshot)
    assert "Wholesale" not in serialized
    assert "sensitive merchant content" not in serialized
    assert queued == [("catora.shopify.webhook", [str(delivery.id)])]
