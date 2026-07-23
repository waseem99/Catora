from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Literal

import boto3
import redis.asyncio as redis
from celery.result import AsyncResult
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auth.service import AuthorizationError
from catora_api.config import Settings
from catora_api.db.models.audit import AuditFinding, AuditRun
from catora_api.db.models.identity import Workspace
from catora_api.db.models.reporting import AuditEvent
from catora_api.demo.pptx import build_demo_pptx
from catora_api.demo.service import DemoService
from catora_api.schemas.demo import (
    DemoComponentView,
    DemoPreflightResponse,
    DemoResetStatusResponse,
    DemoVerifiedSnapshotView,
)
from catora_api.worker import celery_app

DEMO_WORKSPACE_SLUG = "sales-demo"
EXPECTED_PRODUCT_COUNT = 1_000
EXPECTED_VARIANT_COUNT = 2_000


async def require_presenter_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.slug != DEMO_WORKSPACE_SLUG:
        raise AuthorizationError("Presenter operations are limited to the sales demo workspace")
    return workspace


async def _check_redis(settings: Settings) -> None:
    client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_storage(settings: Settings) -> None:
    def check() -> None:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_key=settings.s3_secret_key,
        )
        client.head_bucket(Bucket=settings.s3_bucket)

    await asyncio.to_thread(check)


async def _check_worker() -> None:
    def ping() -> None:
        replies = celery_app.control.inspect(timeout=2).ping()
        if not replies or not any(
            isinstance(payload, dict) and payload.get("ok") == "pong"
            for payload in replies.values()
        ):
            raise RuntimeError("No Celery worker responded")

    await asyncio.to_thread(ping)


async def _component(
    *,
    key: str,
    label: str,
    check: Callable[[], object],
    success_detail: str,
    failure_state: Literal["warning", "error"] = "error",
) -> DemoComponentView:
    try:
        result = check()
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        return DemoComponentView(
            key=key,
            label=label,
            state=failure_state,
            detail=f"Unavailable ({type(exc).__name__})",
        )
    return DemoComponentView(
        key=key,
        label=label,
        state="ok",
        detail=success_detail,
    )


async def build_preflight(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    settings: Settings,
) -> DemoPreflightResponse:
    await require_presenter_workspace(session, workspace_id=workspace_id)
    overview = await DemoService().overview(session, workspace_id=workspace_id)
    audit_run = await session.get(AuditRun, overview.audit.run_id)
    if audit_run is None or audit_run.completed_at is None:
        raise RuntimeError("The verified demo audit run is incomplete")
    snapshot_hash = audit_run.source_snapshot_hash
    if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
        raise RuntimeError("The verified demo audit snapshot is invalid")
    finding_count = int(
        await session.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.workspace_id == workspace_id,
                AuditFinding.audit_run_id == audit_run.id,
            )
        )
        or 0
    )

    data_ready = (
        overview.catalog.product_count >= EXPECTED_PRODUCT_COUNT
        and overview.catalog.variant_count >= EXPECTED_VARIANT_COUNT
        and len(overview.recommendation.fields) >= 1
    )
    data_component = DemoComponentView(
        key="demo_data",
        label="Verified demo data",
        state="ok" if data_ready else "error",
        detail=(
            f"{overview.catalog.product_count:,} products, "
            f"{overview.catalog.variant_count:,} SKUs"
            if data_ready
            else "Enterprise showcase totals or recommendation evidence are incomplete"
        ),
    )

    def check_report() -> None:
        payload = build_demo_pptx(overview)
        if not payload.startswith(b"PK"):
            raise RuntimeError("The executive report is not a valid Office package")

    infrastructure = await asyncio.gather(
        _component(
            key="database",
            label="PostgreSQL",
            check=lambda: None,
            success_detail="Workspace and verified analysis are queryable",
        ),
        _component(
            key="redis",
            label="Redis",
            check=lambda: _check_redis(settings),
            success_detail="Broker and rate-limit store responded",
        ),
        _component(
            key="object_storage",
            label="Object storage",
            check=lambda: _check_storage(settings),
            success_detail="Private catalog bucket is accessible",
        ),
        _component(
            key="worker",
            label="Background worker",
            check=_check_worker,
            success_detail="Celery worker responded to ping",
        ),
        _component(
            key="executive_report",
            label="Executive report",
            check=check_report,
            success_detail="Editable PPTX generated successfully",
        ),
    )
    components = [data_component, *infrastructure]
    return DemoPreflightResponse(
        workspace_id=workspace_id,
        generated_at=overview.generated_at,
        ready=all(component.state == "ok" for component in components),
        components=components,
        last_verified_snapshot=DemoVerifiedSnapshotView(
            audit_run_id=audit_run.id,
            source_snapshot_hash=snapshot_hash,
            verified_at=audit_run.completed_at,
            product_count=overview.catalog.product_count,
            variant_count=overview.catalog.variant_count,
            finding_count=finding_count,
            recommendation_field_count=len(overview.recommendation.fields),
        ),
    )


def enqueue_demo_reset(
    *,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> None:
    from catora_api.demo.tasks import reset_sales_demo

    result = reset_sales_demo.apply_async(
        kwargs={"actor_user_id": str(actor_user_id), "reason": reason},
        task_id=str(task_id),
    )
    if str(result.id) != str(task_id):
        raise RuntimeError("The reset broker returned an unexpected task identity")


def demo_reset_status(task_id: uuid.UUID) -> DemoResetStatusResponse:
    result = AsyncResult(str(task_id), app=celery_app)
    status_map: dict[str, Literal["queued", "running", "completed", "failed"]] = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "RETRY": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
        "REVOKED": "failed",
    }
    status = status_map.get(result.state, "running")
    detail = {
        "queued": "Reset is waiting for an available worker",
        "running": "The deterministic sales demo is being recreated",
        "completed": "The sales demo was reset and verified",
        "failed": "The reset failed; the previous verified snapshot remains available",
    }[status]
    return DemoResetStatusResponse(task_id=task_id, status=status, detail=detail)


async def reset_task_belongs_to_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> bool:
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.event_type == "demo.reset_requested",
            )
            .order_by(AuditEvent.occurred_at.desc())
            .limit(50)
        )
    ).all()
    return any(event.payload.get("task_id") == str(task_id) for event in events)
