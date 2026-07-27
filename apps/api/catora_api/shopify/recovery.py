from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent, IngestionJob, ReportJob

MAX_SHOPIFY_SYNC_RETRIES = 3
SHOPIFY_SYNC_RETRY_DELAYS_SECONDS = (60, 300, 900)


@dataclass(frozen=True, slots=True)
class ShopifySyncRetryDecision:
    retry: bool
    countdown_seconds: int | None
    attempt_number: int
    retry_count: int
    dead_lettered: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _bounded_error_type(error: BaseException) -> str:
    return type(error).__name__[:120]


def _retry_delay(retries_already_used: int) -> int:
    index = min(
        max(retries_already_used, 0),
        len(SHOPIFY_SYNC_RETRY_DELAYS_SECONDS) - 1,
    )
    return SHOPIFY_SYNC_RETRY_DELAYS_SECONDS[index]


async def record_shopify_sync_failure(
    session: AsyncSession,
    *,
    installation: ReportJob,
    ingestion_job: IngestionJob,
    retries_already_used: int,
    error: BaseException,
    now: datetime | None = None,
) -> ShopifySyncRetryDecision:
    timestamp = now or _now()
    snapshot = dict(installation.input_snapshot)
    attempt_number = max(retries_already_used, 0) + 1
    scope_blocked = snapshot.get("scope_reauthorization_required") is True
    retry_eligible = (
        installation.status == "active"
        and ingestion_job.status != "cancelled"
        and not scope_blocked
    )
    retry = retry_eligible and retries_already_used < MAX_SHOPIFY_SYNC_RETRIES
    retry_count = min(attempt_number, MAX_SHOPIFY_SYNC_RETRIES)
    delay = _retry_delay(retries_already_used) if retry else None
    next_retry_at = (
        timestamp + timedelta(seconds=delay) if delay is not None else None
    )
    dead_lettered = retry_eligible and not retry
    error_type = _bounded_error_type(error)

    installation.input_snapshot = {
        **snapshot,
        "sync_status": "failed",
        "sync_attempt_count": attempt_number,
        "sync_retry_count": retry_count,
        "sync_retry_scheduled_at": timestamp.isoformat() if retry else None,
        "sync_next_retry_at": (
            next_retry_at.isoformat() if next_retry_at is not None else None
        ),
        "sync_last_failure_at": timestamp.isoformat(),
        "sync_last_failure_type": error_type,
        "sync_dead_lettered_at": timestamp.isoformat() if dead_lettered else None,
        "sync_recovery_required": dead_lettered,
        "last_sync_failed_at": timestamp.isoformat(),
        "last_sync_error_type": error_type,
    }
    session.add(
        AuditEvent(
            workspace_id=installation.workspace_id,
            actor_user_id=None,
            event_type=(
                "shopify.sync_retry_scheduled"
                if retry
                else "shopify.sync_dead_lettered"
                if dead_lettered
                else "shopify.sync_retry_suppressed"
            ),
            entity_type="ingestion_job",
            entity_id=ingestion_job.id,
            payload={
                "installation_id": str(installation.id),
                "attempt_number": attempt_number,
                "retry_count": retry_count,
                "countdown_seconds": delay,
                "error_type": error_type,
                "scope_blocked": scope_blocked,
                "installation_status": installation.status,
            },
        )
    )
    await session.commit()
    return ShopifySyncRetryDecision(
        retry=retry,
        countdown_seconds=delay,
        attempt_number=attempt_number,
        retry_count=retry_count,
        dead_lettered=dead_lettered,
    )


async def mark_shopify_sync_recovered(
    session: AsyncSession,
    *,
    installation: ReportJob,
    ingestion_job: IngestionJob,
    now: datetime | None = None,
) -> bool:
    snapshot = dict(installation.input_snapshot)
    had_recovery_state = any(
        snapshot.get(key) not in {None, 0, False}
        for key in (
            "sync_retry_count",
            "sync_retry_scheduled_at",
            "sync_next_retry_at",
            "sync_dead_lettered_at",
            "sync_recovery_required",
        )
    )
    if not had_recovery_state:
        return False
    timestamp = now or _now()
    prior_retry_count = snapshot.get("sync_retry_count")
    installation.input_snapshot = {
        **snapshot,
        "sync_attempt_count": 0,
        "sync_retry_count": 0,
        "sync_retry_scheduled_at": None,
        "sync_next_retry_at": None,
        "sync_last_failure_at": None,
        "sync_last_failure_type": None,
        "sync_dead_lettered_at": None,
        "sync_recovery_required": False,
        "sync_recovered_at": timestamp.isoformat(),
    }
    session.add(
        AuditEvent(
            workspace_id=installation.workspace_id,
            actor_user_id=None,
            event_type="shopify.sync_recovered",
            entity_type="ingestion_job",
            entity_id=ingestion_job.id,
            payload={
                "installation_id": str(installation.id),
                "prior_retry_count": (
                    prior_retry_count if isinstance(prior_retry_count, int) else 0
                ),
            },
        )
    )
    await session.commit()
    return True


async def prepare_shopify_operator_recovery(
    session: AsyncSession,
    *,
    installation: ReportJob,
    actor_user_id: uuid.UUID,
    now: datetime | None = None,
) -> None:
    snapshot = dict(installation.input_snapshot)
    timestamp = now or _now()
    installation.input_snapshot = {
        **snapshot,
        "sync_attempt_count": 0,
        "sync_retry_count": 0,
        "sync_retry_scheduled_at": None,
        "sync_next_retry_at": None,
        "sync_dead_lettered_at": None,
        "sync_recovery_required": False,
        "sync_recovery_requested_at": timestamp.isoformat(),
        "sync_recovery_requested_by_user_id": str(actor_user_id),
    }
    session.add(
        AuditEvent(
            workspace_id=installation.workspace_id,
            actor_user_id=actor_user_id,
            event_type="shopify.sync_recovery_requested",
            entity_type="report_job",
            entity_id=installation.id,
            payload={
                "shop_domain": snapshot.get("shop_domain"),
                "prior_error_type": snapshot.get("last_sync_error_type"),
            },
        )
    )
    await session.commit()
