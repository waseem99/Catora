from __future__ import annotations

import asyncio
import uuid
from typing import cast

from celery import shared_task
from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models import IngestionJob, Membership, ReportJob, Workspace
from catora_api.shopify.analysis import (
    mark_shopify_analysis_failed,
    run_shopify_analysis,
    should_run_shopify_analysis,
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


@shared_task(
    name="catora.shopify.sync_and_analyze",
    ignore_result=True,
)  # type: ignore[misc]
def run_shopify_sync_and_analysis(job_id: str, installation_id: str) -> None:
    asyncio.run(
        _run_shopify_sync_and_analysis(
            uuid.UUID(job_id),
            uuid.UUID(installation_id),
        )
    )


async def _run_shopify_sync_and_analysis(
    job_id: uuid.UUID,
    installation_id: uuid.UUID,
) -> None:
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
            return
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
                assigned_category_count=int(
                    snapshot.get("assigned_category_count") or 0
                ),
                ambiguous_category_count=int(
                    snapshot.get("ambiguous_category_count") or 0
                ),
                unclassified_category_count=int(
                    snapshot.get("unclassified_category_count") or 0
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
