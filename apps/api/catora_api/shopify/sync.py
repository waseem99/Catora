from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    IngestionJob,
    ReportJob,
    ShopifyStoreInvitation,
)
from catora_api.worker import celery_app

ACTIVE_JOB_STATUSES = ("queued", "validating", "running")


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_value(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _text_value(snapshot: dict[str, object], key: str) -> str | None:
    value = snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _string_list(snapshot: dict[str, object], key: str) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


async def _installation_actor(
    session: AsyncSession,
    *,
    installation: ReportJob,
    snapshot: dict[str, object],
    actor_user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if actor_user_id is not None:
        return actor_user_id
    persisted = _uuid_value(snapshot, "installed_by_user_id")
    if persisted is not None:
        return persisted
    audited = await session.scalar(
        select(AuditEvent.actor_user_id)
        .where(
            AuditEvent.entity_id == installation.id,
            AuditEvent.event_type.in_(("shopify.installed", "shopify.reconnected")),
            AuditEvent.actor_user_id.is_not(None),
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(1)
    )
    if audited is not None:
        return audited
    if snapshot.get("distribution") != "public":
        return None
    shop_domain = _text_value(snapshot, "shop_domain")
    if shop_domain is None:
        return None
    return await session.scalar(
        select(ShopifyStoreInvitation.created_by_user_id)
        .where(
            ShopifyStoreInvitation.activated_workspace_id == installation.workspace_id,
            ShopifyStoreInvitation.shop_domain == shop_domain,
            ShopifyStoreInvitation.status == "activated",
        )
        .limit(1)
    )


async def queue_shopify_sync(
    session: AsyncSession,
    *,
    installation: ReportJob,
    reason: str,
    actor_user_id: uuid.UUID | None = None,
    product_ids: Sequence[str] = (),
    full_reconciliation: bool = False,
) -> IngestionJob | None:
    if installation.status != "active":
        return None
    workspace_id = cast(uuid.UUID, installation.workspace_id)
    snapshot = dict(installation.input_snapshot)
    actor_user_id = await _installation_actor(
        session,
        installation=installation,
        snapshot=snapshot,
        actor_user_id=actor_user_id,
    )
    if actor_user_id is not None:
        snapshot["installed_by_user_id"] = str(actor_user_id)

    source_id = _uuid_value(snapshot, "catalog_source_id")
    if source_id is None:
        return None
    source = await session.get(CatalogSource, source_id)
    if source is None or source.credential_ref is None or source.status != "ready":
        return None

    active_job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.workspace_id == workspace_id,
            IngestionJob.catalog_source_id == source.id,
            IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    bounded_ids = [value for value in product_ids if value][:100]
    if active_job is not None:
        pending = _string_list(snapshot, "pending_product_ids")
        installation.input_snapshot = {
            **snapshot,
            "sync_status": "coalesced",
            "pending_product_ids": list(dict.fromkeys([*pending, *bounded_ids]))[:100],
            "pending_full_reconciliation": (
                snapshot.get("pending_full_reconciliation") is True
                or full_reconciliation
            ),
            "last_sync_requested_at": _now().isoformat(),
            "last_sync_reason": reason,
        }
        await session.commit()
        return active_job

    last_success = _text_value(snapshot, "last_successful_sync_at")
    updated_after: str | None = None
    if not full_reconciliation and last_success is not None:
        try:
            parsed = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
            updated_after = (parsed - timedelta(minutes=5)).isoformat()
        except ValueError:
            updated_after = None
    source.config = {
        **dict(source.config),
        "updated_after": updated_after,
    }
    job = IngestionJob(
        workspace_id=workspace_id,
        catalog_source_id=source.id,
        status="queued",
        checkpoint={
            "shopify": {
                "reason": reason,
                "product_ids": bounded_ids,
                "full_reconciliation": full_reconciliation,
                "queued_at": _now().isoformat(),
            }
        },
    )
    session.add(job)
    await session.flush()
    installation.input_snapshot = {
        **snapshot,
        "sync_status": "queued",
        "last_sync_requested_at": _now().isoformat(),
        "last_sync_reason": reason,
        "last_sync_job_id": str(job.id),
        "last_sync_full_reconciliation": full_reconciliation,
        "pending_product_ids": [],
        "pending_full_reconciliation": False,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            event_type="shopify.sync_queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            payload={
                "catalog_source_id": str(source.id),
                "reason": reason,
                "product_id_count": len(bounded_ids),
                "full_reconciliation": full_reconciliation,
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task(
            "catora.shopify.sync",
            args=[str(job.id), str(installation.id)],
        )
    except Exception as exc:
        job.status = "failed"
        job.checkpoint = {
            **dict(job.checkpoint),
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue Shopify synchronization",
        }
        installation.input_snapshot = {
            **dict(installation.input_snapshot),
            "sync_status": "failed",
            "last_sync_error_type": type(exc).__name__,
        }
        await session.commit()
        return None
    return job
