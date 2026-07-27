from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any, cast

import pytest

from catora_api.config import Settings
from catora_api.db.models import AuditEvent, ReportJob
from catora_api.shopify.webhooks import ShopifyWebhookError, receive_shopify_webhook


class ScalarList:
    def __init__(self, values: list[ReportJob]) -> None:
        self.values = values

    def all(self) -> list[ReportJob]:
        return self.values


class ExecuteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class ScopeSession:
    def __init__(
        self,
        installation: ReportJob,
        *,
        cancelled_jobs: int = 0,
    ) -> None:
        self.installation = installation
        self.cancelled_jobs = cancelled_jobs
        self.added: list[object] = []
        self.commit_count = 0
        self.execute_count = 0

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    async def scalars(self, _statement: object) -> ScalarList:
        return ScalarList([self.installation])

    async def execute(self, _statement: object) -> ExecuteResult:
        self.execute_count += 1
        return ExecuteResult(self.cancelled_jobs)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        shopify_enabled=False,
        shopify_public_enabled=True,
        shopify_public_client_id="public-client-123456",
        shopify_public_client_secret="p" * 32,
    )


def _signature(body: bytes) -> str:
    digest = hmac.new(b"p" * 32, body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _installation(
    *,
    status: str = "active",
    snapshot: dict[str, object] | None = None,
) -> ReportJob:
    source_id = uuid.uuid4()
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status=status,
        input_snapshot={
            "distribution": "public",
            "shop_domain": "prospect-store.myshopify.com",
            "catalog_source_id": str(source_id),
            "granted_scopes": ["read_products"],
            "sync_status": "completed",
            **(snapshot or {}),
        },
        template_version="shopify-public-installation-v1",
    )


async def _deliver(
    session: ScopeSession,
    payload: dict[str, object],
    *,
    webhook_id: str,
) -> ReportJob:
    body = json.dumps(payload).encode()
    receipt = await receive_shopify_webhook(
        cast(Any, session),
        settings=_settings(),
        body=body,
        topic="app/scopes_update",
        shop_domain="prospect-store.myshopify.com",
        webhook_id=webhook_id,
        event_id=None,
        triggered_at="2026-07-24T16:30:01Z",
        supplied_signature=_signature(body),
    )
    assert receipt.duplicate is False
    return next(
        cast(ReportJob, item)
        for item in session.added
        if isinstance(item, ReportJob)
        and item.report_type == "shopify_webhook_delivery"
    )


@pytest.mark.asyncio
async def test_exact_read_scope_remains_active_and_records_bounded_metadata() -> None:
    installation = _installation()
    session = ScopeSession(installation)

    delivery = await _deliver(
        session,
        {
            "id": 1,
            "shop_id": "gid://shopify/Shop/548380009",
            "previous": ["read_products"],
            "current": ["read_products"],
            "updated_at": "2026-07-24T16:30:00.000Z",
            "unexpected_secret": "must-not-be-persisted",
        },
        webhook_id="scope-still-compliant",
    )

    assert installation.status == "active"
    assert installation.input_snapshot["granted_scopes"] == ["read_products"]
    assert installation.input_snapshot["scope_reauthorization_required"] is False
    assert installation.input_snapshot["sync_status"] == "completed"
    assert session.execute_count == 0
    assert session.commit_count == 1
    assert delivery.status == "completed"
    serialized = json.dumps(delivery.input_snapshot)
    assert "must-not-be-persisted" not in serialized
    assert "payload_sha256" in delivery.input_snapshot
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.payload["scope_compliant"] is True


@pytest.mark.asyncio
async def test_extra_write_scope_blocks_sync_and_cancels_active_jobs() -> None:
    installation = _installation(
        snapshot={
            "pending_product_ids": ["gid://shopify/Product/1"],
            "pending_full_reconciliation": True,
        }
    )
    session = ScopeSession(installation, cancelled_jobs=2)

    delivery = await _deliver(
        session,
        {
            "id": 1,
            "shop_id": "gid://shopify/Shop/548380009",
            "previous": ["read_products"],
            "current": ["read_products", "write_products"],
            "updated_at": "2026-07-24T16:31:00.000Z",
        },
        webhook_id="scope-write-added",
    )

    assert installation.status == "refresh_required"
    assert installation.input_snapshot["granted_scopes"] == [
        "read_products",
        "write_products",
    ]
    assert installation.input_snapshot["scope_reauthorization_required"] is True
    assert installation.input_snapshot["sync_status"] == "reauthorization_required"
    assert installation.input_snapshot["last_sync_error_type"] == "ShopifyScopeMismatch"
    assert installation.input_snapshot["pending_product_ids"] == []
    assert installation.input_snapshot["pending_full_reconciliation"] is False
    assert session.execute_count == 1
    assert delivery.input_snapshot["cancelled_job_count"] == 2
    assert delivery.input_snapshot["scope_compliant"] is False


@pytest.mark.asyncio
async def test_restored_exact_scope_reactivates_scope_blocked_installation() -> None:
    installation = _installation(
        status="refresh_required",
        snapshot={
            "granted_scopes": ["read_products", "write_products"],
            "scope_reauthorization_required": True,
            "sync_status": "reauthorization_required",
            "last_sync_error_type": "ShopifyScopeMismatch",
        },
    )
    session = ScopeSession(installation)

    await _deliver(
        session,
        {
            "id": 1,
            "shop_id": "gid://shopify/Shop/548380009",
            "previous": ["read_products", "write_products"],
            "current": ["read_products"],
            "updated_at": "2026-07-24T16:32:00.000Z",
        },
        webhook_id="scope-restored",
    )

    assert installation.status == "active"
    assert installation.input_snapshot["scope_reauthorization_required"] is False
    assert installation.input_snapshot["sync_status"] == "not_started"
    assert installation.input_snapshot["last_sync_error_type"] is None
    assert session.execute_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"previous": ["read_products"], "current": "read_products"},
        {"previous": [], "current": ["read_products", ""]},
        {
            "previous": [],
            "current": ["read_products"],
            "shop_id": "548380009",
        },
    ],
)
async def test_invalid_scope_payload_fails_before_persistence(
    payload: dict[str, object],
) -> None:
    installation = _installation()
    session = ScopeSession(installation)
    body = json.dumps(payload).encode()

    with pytest.raises(ShopifyWebhookError, match="scope update payload is invalid"):
        await receive_shopify_webhook(
            cast(Any, session),
            settings=_settings(),
            body=body,
            topic="app/scopes_update",
            shop_domain="prospect-store.myshopify.com",
            webhook_id="invalid-scope-payload",
            event_id=None,
            triggered_at=None,
            supplied_signature=_signature(body),
        )

    assert session.added == []
    assert session.commit_count == 0
    assert installation.status == "active"
