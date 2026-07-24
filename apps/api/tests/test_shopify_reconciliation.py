from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, cast

import pytest

from catora_api.db.models import CatalogSource, IngestionJob, ReportJob
from catora_api.shopify import sync, tasks
from catora_api.shopify.sync import queue_shopify_sync
from catora_api.shopify.webhooks import SHOPIFY_WEBHOOK_DELIVERY_TYPE
from catora_api.worker import celery_app


class SyncSession:
    def __init__(
        self,
        source: CatalogSource,
        *,
        active_job: IngestionJob | None = None,
    ) -> None:
        self.source = source
        self.active_job = active_job
        self.added: list[object] = []
        self.commit_count = 0

    async def get(self, model: object, identifier: object) -> object | None:
        if model is CatalogSource and identifier == self.source.id:
            return self.source
        return None

    async def scalar(self, _statement: object) -> IngestionJob | None:
        return self.active_job

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for item in self.added:
            if isinstance(item, IngestionJob) and item.id is None:
                item.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_count += 1


class TaskSession:
    def __init__(self, delivery: ReportJob, installation: ReportJob) -> None:
        self.delivery = delivery
        self.installation = installation
        self.commit_count = 0

    async def get(self, model: object, identifier: object) -> object | None:
        if model is ReportJob and identifier == self.delivery.id:
            return self.delivery
        if model is ReportJob and identifier == self.installation.id:
            return self.installation
        return None

    async def commit(self) -> None:
        self.commit_count += 1


class TaskSessionContext(AbstractAsyncContextManager[TaskSession]):
    def __init__(self, session: TaskSession) -> None:
        self.session = session

    async def __aenter__(self) -> TaskSession:
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def installation(source: CatalogSource) -> ReportJob:
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=source.workspace_id,
        report_type="shopify_installation",
        status="active",
        input_snapshot={
            "catalog_source_id": str(source.id),
            "shop_domain": "prospect-store.myshopify.com",
            "distribution": "public",
            "last_successful_sync_at": "2026-07-24T10:00:00+00:00",
        },
        template_version="shopify-public-installation-v1",
    )


def source(*, status: str = "active") -> CatalogSource:
    return CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Shopify catalog",
        source_type="shopify",
        status=status,
        credential_ref=f"shopify-public-installation:{uuid.uuid4()}",
        config={
            "shop_domain": "prospect-store.myshopify.com",
            "distribution": "public",
            "updated_after": "2026-07-24T10:00:00+00:00",
        },
    )


@pytest.mark.asyncio
async def test_active_source_can_queue_incremental_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_source = source(status="active")
    app_installation = installation(catalog_source)
    session = SyncSession(catalog_source)
    queued: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        sync.celery_app,
        "send_task",
        lambda name, args: queued.append((name, args)),
    )

    job = await queue_shopify_sync(
        cast(Any, session),
        installation=app_installation,
        reason="scheduled_incremental_reconciliation",
        actor_user_id=uuid.uuid4(),
    )

    assert job is not None
    assert job.checkpoint["shopify"]["full_reconciliation"] is False
    assert catalog_source.config["updated_after"] == "2026-07-24T09:55:00+00:00"
    assert app_installation.input_snapshot["sync_status"] == "queued"
    assert queued == [
        ("catora.shopify.sync", [str(job.id), str(app_installation.id)])
    ]


@pytest.mark.asyncio
async def test_full_reconciliation_clears_incremental_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_source = source(status="active")
    app_installation = installation(catalog_source)
    session = SyncSession(catalog_source)
    monkeypatch.setattr(sync.celery_app, "send_task", lambda *_args, **_kwargs: None)

    job = await queue_shopify_sync(
        cast(Any, session),
        installation=app_installation,
        reason="scheduled_full_reconciliation",
        actor_user_id=uuid.uuid4(),
        full_reconciliation=True,
    )

    assert job is not None
    assert catalog_source.config["updated_after"] is None
    assert job.checkpoint["shopify"]["full_reconciliation"] is True
    assert app_installation.input_snapshot["last_sync_full_reconciliation"] is True


@pytest.mark.asyncio
async def test_full_reconciliation_is_preserved_when_job_is_active() -> None:
    catalog_source = source(status="active")
    app_installation = installation(catalog_source)
    active_job = IngestionJob(
        id=uuid.uuid4(),
        workspace_id=catalog_source.workspace_id,
        catalog_source_id=catalog_source.id,
        status="running",
        checkpoint={},
    )
    session = SyncSession(catalog_source, active_job=active_job)

    returned = await queue_shopify_sync(
        cast(Any, session),
        installation=app_installation,
        reason="scheduled_full_reconciliation",
        actor_user_id=uuid.uuid4(),
        full_reconciliation=True,
    )

    assert returned is active_job
    assert app_installation.input_snapshot["sync_status"] == "coalesced"
    assert app_installation.input_snapshot["pending_full_reconciliation"] is True
    assert session.added == []


def test_worker_schedules_incremental_and_daily_full_reconciliation() -> None:
    schedule = celery_app.conf.beat_schedule
    assert schedule["shopify-incremental-reconciliation"]["task"] == (
        "catora.shopify.reconcile_incremental"
    )
    assert schedule["shopify-full-reconciliation"]["task"] == (
        "catora.shopify.reconcile_full"
    )


@pytest.mark.asyncio
async def test_bulk_finish_delivery_updates_bounded_installation_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    operation_id = "gid://shopify/BulkOperation/9001"
    app_installation = ReportJob(
        id=installation_id,
        workspace_id=workspace_id,
        report_type="shopify_installation",
        status="active",
        input_snapshot={
            "distribution": "public",
            "shop_domain": "prospect-store.myshopify.com",
        },
        template_version="shopify-public-installation-v1",
    )
    delivery = ReportJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        report_type=SHOPIFY_WEBHOOK_DELIVERY_TYPE,
        status="queued",
        input_snapshot={
            "installation_id": str(installation_id),
            "topic": "bulk_operations/finish",
            "bulk_operation_id": operation_id,
            "bulk_status": "completed",
            "bulk_completed_at": "2026-07-24T14:00:00Z",
            "bulk_error_code": None,
        },
        template_version="shopify-webhook-v3",
    )
    session = TaskSession(delivery, app_installation)
    monkeypatch.setattr(tasks, "SessionFactory", lambda: TaskSessionContext(session))

    await tasks._process_shopify_webhook(delivery.id)

    snapshot = app_installation.input_snapshot
    assert snapshot["last_bulk_operation_id"] == operation_id
    assert snapshot["last_bulk_operation_status"] == "completed"
    assert snapshot["last_bulk_operation_completed_at"] == (
        "2026-07-24T14:00:00Z"
    )
    assert isinstance(snapshot["last_bulk_webhook_received_at"], str)
    assert delivery.status == "completed"
    assert session.commit_count == 1


def test_job_full_reconciliation_marker_is_strict() -> None:
    full = IngestionJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        catalog_source_id=uuid.uuid4(),
        status="completed",
        checkpoint={"shopify": {"full_reconciliation": True}},
    )
    incremental = IngestionJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        catalog_source_id=uuid.uuid4(),
        status="completed",
        checkpoint={"shopify": {"full_reconciliation": False}},
    )

    assert tasks._job_full_reconciliation(full) is True
    assert tasks._job_full_reconciliation(incremental) is False
