from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.db.models import AuditEvent, IngestionJob, ReportJob
from catora_api.shopify.recovery import (
    MAX_SHOPIFY_SYNC_RETRIES,
    mark_shopify_sync_recovered,
    prepare_shopify_operator_recovery,
    record_shopify_sync_failure,
)


class RecoverySession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


def _installation(
    *,
    status: str = "active",
    snapshot: dict[str, object] | None = None,
) -> ReportJob:
    return ReportJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        report_type="shopify_installation",
        status=status,
        input_snapshot={
            "distribution": "public",
            "shop_domain": "prospect-store.myshopify.com",
            "sync_status": "failed",
            **(snapshot or {}),
        },
        template_version="shopify-public-installation-v1",
    )


def _job(*, status: str = "failed") -> IngestionJob:
    return IngestionJob(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        catalog_source_id=uuid.uuid4(),
        status=status,
        checkpoint={},
    )


@pytest.mark.asyncio
async def test_first_failure_schedules_bounded_retry_without_error_message() -> None:
    session = RecoverySession()
    installation = _installation()
    job = _job()
    now = datetime(2026, 7, 27, 5, 30, tzinfo=UTC)
    error = RuntimeError("secret-bearing upstream response must not persist")

    decision = await record_shopify_sync_failure(
        cast(Any, session),
        installation=installation,
        ingestion_job=job,
        retries_already_used=0,
        error=error,
        now=now,
    )

    assert decision.retry is True
    assert decision.countdown_seconds == 60
    assert decision.attempt_number == 1
    assert decision.retry_count == 1
    assert decision.dead_lettered is False
    snapshot = dict(installation.input_snapshot)
    assert snapshot["sync_retry_count"] == 1
    assert snapshot["sync_next_retry_at"] == "2026-07-27T05:31:00+00:00"
    assert snapshot["sync_recovery_required"] is False
    serialized = json.dumps(snapshot)
    assert "secret-bearing" not in serialized
    assert snapshot["sync_last_failure_type"] == "RuntimeError"
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "shopify.sync_retry_scheduled"
    assert audit.payload["countdown_seconds"] == 60
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_exhausted_retries_dead_letter_installation() -> None:
    session = RecoverySession()
    installation = _installation()
    job = _job()
    now = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)

    decision = await record_shopify_sync_failure(
        cast(Any, session),
        installation=installation,
        ingestion_job=job,
        retries_already_used=MAX_SHOPIFY_SYNC_RETRIES,
        error=TimeoutError("upstream timeout"),
        now=now,
    )

    assert decision.retry is False
    assert decision.countdown_seconds is None
    assert decision.dead_lettered is True
    snapshot = dict(installation.input_snapshot)
    assert snapshot["sync_retry_count"] == MAX_SHOPIFY_SYNC_RETRIES
    assert snapshot["sync_dead_lettered_at"] == "2026-07-27T06:00:00+00:00"
    assert snapshot["sync_recovery_required"] is True
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "shopify.sync_dead_lettered"


@pytest.mark.asyncio
async def test_scope_blocked_installation_is_not_retried_or_dead_lettered() -> None:
    session = RecoverySession()
    installation = _installation(
        status="refresh_required",
        snapshot={"scope_reauthorization_required": True},
    )
    job = _job()

    decision = await record_shopify_sync_failure(
        cast(Any, session),
        installation=installation,
        ingestion_job=job,
        retries_already_used=0,
        error=RuntimeError("scope mismatch"),
    )

    assert decision.retry is False
    assert decision.dead_lettered is False
    assert installation.input_snapshot["sync_recovery_required"] is False
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "shopify.sync_retry_suppressed"
    assert audit.payload["scope_blocked"] is True


@pytest.mark.asyncio
async def test_success_clears_retry_and_dead_letter_state() -> None:
    session = RecoverySession()
    installation = _installation(
        snapshot={
            "sync_status": "completed",
            "sync_attempt_count": 4,
            "sync_retry_count": 3,
            "sync_retry_scheduled_at": "2026-07-27T05:00:00+00:00",
            "sync_next_retry_at": "2026-07-27T05:15:00+00:00",
            "sync_dead_lettered_at": "2026-07-27T05:20:00+00:00",
            "sync_recovery_required": True,
        }
    )
    job = _job(status="completed")
    now = datetime(2026, 7, 27, 6, 30, tzinfo=UTC)

    changed = await mark_shopify_sync_recovered(
        cast(Any, session),
        installation=installation,
        ingestion_job=job,
        now=now,
    )

    assert changed is True
    snapshot = dict(installation.input_snapshot)
    assert snapshot["sync_attempt_count"] == 0
    assert snapshot["sync_retry_count"] == 0
    assert snapshot["sync_next_retry_at"] is None
    assert snapshot["sync_dead_lettered_at"] is None
    assert snapshot["sync_recovery_required"] is False
    assert snapshot["sync_recovered_at"] == "2026-07-27T06:30:00+00:00"
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "shopify.sync_recovered"


@pytest.mark.asyncio
async def test_operator_request_preserves_dead_letter_until_recovery_succeeds() -> None:
    session = RecoverySession()
    actor = uuid.uuid4()
    installation = _installation(
        snapshot={
            "sync_retry_count": 3,
            "sync_dead_lettered_at": "2026-07-27T05:20:00+00:00",
            "sync_recovery_required": True,
            "last_sync_error_type": "TimeoutError",
        }
    )

    await prepare_shopify_operator_recovery(
        cast(Any, session),
        installation=installation,
        actor_user_id=actor,
        now=datetime(2026, 7, 27, 7, 0, tzinfo=UTC),
    )

    snapshot = dict(installation.input_snapshot)
    assert snapshot["sync_retry_count"] == 3
    assert snapshot["sync_dead_lettered_at"] == "2026-07-27T05:20:00+00:00"
    assert snapshot["sync_recovery_required"] is True
    assert snapshot["sync_recovery_requested_at"] == "2026-07-27T07:00:00+00:00"
    assert snapshot["sync_recovery_requested_by_user_id"] == str(actor)
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "shopify.sync_recovery_requested"
    assert audit.actor_user_id == actor
