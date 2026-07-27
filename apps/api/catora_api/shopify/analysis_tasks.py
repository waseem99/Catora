from __future__ import annotations

import asyncio
import uuid
from typing import cast

from celery import Task, shared_task
from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models import IngestionJob, Membership, ReportJob, Workspace
from catora_api.shopify.analysis import (
    mark_shopify_analysis_failed,
    run_shopify_analysis,
    should_run_shopify_analysis,
)
from catora_api.shopify.recovery import (
    MAX_SHOPIFY_SYNC_RETRIES,
    ShopifySyncRetryDecision,
    mark_shopify_sync_recovered,
    record_shopify_sync_failure,
)
from catora_api.shopify.tasks import _run_shopify_sync


def _uuid_value(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _nonnegative_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


async def _ensure_operator_membership(
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    async with SessionFactory() as session:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None:
            raise RuntimeError("Shopify prospect workspace is unavailable")
        membership = await session.scalar(
            select(Membership).where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
            )
        )
        if membership is None:
            session.add(
                Membership(
                    organization_id=workspace.organization_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role="admin",
                )
            )
            await session.commit()


async def _sync_stage_is_complete(
    job_id: uuid.UUID,
    installation_id: uuid.UUID,
) -> bool:
    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        ingestion_job = await session.get(IngestionJob, job_id)
        if installation is None or ingestion_job is None:
            return False
        snapshot = dict(installation.input_snapshot)
        return (
            installation.status == "active"
            and ingestion_job.status in {"completed", "partially_completed"}
            and snapshot.get("last_sync_job_id") == str(job_id)
            and snapshot.get("sync_status") == "completed"
        )


async def _record_task_failure(
    *,
    job_id: uuid.UUID,
    installation_id: uuid.UUID,
    retries_already_used: int,
    error: BaseException,
) -> ShopifySyncRetryDecision | None:
    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        ingestion_job = await session.get(IngestionJob, job_id)
        if installation is None or ingestion_job is None:
            return None
        return await record_shopify_sync_failure(
            session,
            installation=installation,
            ingestion_job=ingestion_job,
            retries_already_used=retries_already_used,
            error=error,
        )


async def _mark_task_recovered(
    *,
    job_id: uuid.UUID,
    installation_id: uuid.UUID,
) -> None:
    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        ingestion_job = await session.get(IngestionJob, job_id)
        if installation is None or ingestion_job is None:
            return
        snapshot = dict(installation.input_snapshot)
        if (
            installation.status != "active"
            or ingestion_job.status not in {"completed", "partially_completed"}
            or snapshot.get("sync_status") != "completed"
            or snapshot.get("analysis_status") == "failed"
        ):
            return
        await mark_shopify_sync_recovered(
            session,
            installation=installation,
            ingestion_job=ingestion_job,
        )


@shared_task(
    bind=True,
    name="catora.shopify.sync_and_analyze",
    ignore_result=True,
    max_retries=MAX_SHOPIFY_SYNC_RETRIES,
)  # type: ignore[misc]
def run_shopify_sync_and_analysis(
    task: Task,
    job_id: str,
    installation_id: str,
) -> None:
    parsed_job_id = uuid.UUID(job_id)
    parsed_installation_id = uuid.UUID(installation_id)
    try:
        asyncio.run(
            _run_shopify_sync_and_analysis(
                parsed_job_id,
                parsed_installation_id,
            )
        )
    except Exception as exc:
        retries_already_used = int(getattr(task.request, "retries", 0) or 0)
        decision = asyncio.run(
            _record_task_failure(
                job_id=parsed_job_id,
                installation_id=parsed_installation_id,
                retries_already_used=retries_already_used,
                error=exc,
            )
        )
        if decision is not None and decision.retry:
            raise task.retry(
                exc=exc,
                countdown=decision.countdown_seconds,
            ) from exc
        raise
    asyncio.run(
        _mark_task_recovered(
            job_id=parsed_job_id,
            installation_id=parsed_installation_id,
        )
    )


async def _run_shopify_sync_and_analysis(
    job_id: uuid.UUID,
    installation_id: uuid.UUID,
) -> None:
    if not await _sync_stage_is_complete(job_id, installation_id):
        await _run_shopify_sync(job_id, installation_id)

    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        ingestion_job = await session.get(IngestionJob, job_id)
        if (
            installation is None
            or ingestion_job is None
            or installation.status != "active"
            or installation.input_snapshot.get("distribution") != "public"
            or installation.input_snapshot.get("sync_status") != "completed"
        ):
            return
        snapshot = dict(installation.input_snapshot)
        if not should_run_shopify_analysis(installation, ingestion_job):
            if _uuid_value(snapshot, "last_verified_analysis_report_job_id") is not None:
                installation.input_snapshot = {
                    **snapshot,
                    "analysis_status": "completed",
                    "analysis_stale": False,
                    "analysis_error_type": None,
                }
                await session.commit()
            return
        actor_user_id = _uuid_value(snapshot, "installed_by_user_id")
        audit_run_id = _uuid_value(snapshot, "last_audit_run_id")
        if actor_user_id is None or audit_run_id is None:
            error = RuntimeError("Shopify analysis prerequisites are unavailable")
            await mark_shopify_analysis_failed(
                session,
                installation=installation,
                error=error,
            )
            raise error
        workspace_id = cast(uuid.UUID, installation.workspace_id)

    await _ensure_operator_membership(
        workspace_id=workspace_id,
        user_id=actor_user_id,
    )

    async with SessionFactory() as session:
        installation = await session.get(ReportJob, installation_id)
        ingestion_job = await session.get(IngestionJob, job_id)
        if installation is None or ingestion_job is None:
            return
        snapshot = dict(installation.input_snapshot)
        try:
            await run_shopify_analysis(
                session,
                installation=installation,
                ingestion_job=ingestion_job,
                audit_run_id=audit_run_id,
                actor_user_id=actor_user_id,
                assigned_category_count=_nonnegative_int(
                    snapshot,
                    "assigned_category_count",
                ),
                ambiguous_category_count=_nonnegative_int(
                    snapshot,
                    "ambiguous_category_count",
                ),
                unclassified_category_count=_nonnegative_int(
                    snapshot,
                    "unclassified_category_count",
                ),
            )
        except Exception as exc:
            await session.rollback()
            installation = await session.get(ReportJob, installation_id)
            if installation is not None:
                await mark_shopify_analysis_failed(
                    session,
                    installation=installation,
                    error=exc,
                )
            raise
