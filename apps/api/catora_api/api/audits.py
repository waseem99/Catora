from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from catora_api.auditing.service import (
    AuditConfigurationError,
    AuditRunConflictError,
    AuditRunNotFoundError,
    AuditRunService,
)
from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models import AuditEvent, AuditFinding, AuditRun
from catora_api.schemas.audits import (
    AuditFindingView,
    AuditRunCreateRequest,
    AuditRunView,
)
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["catalog audits"])
audit_service = AuditRunService()


def _require_audit_run(role: str) -> None:
    if not can(Role(role), "analysis.run"):
        raise AuthorizationError("Audit execution permission required")


def _run_view(run: AuditRun) -> AuditRunView:
    return AuditRunView.model_validate(run)


@router.post(
    "/workspaces/{workspace_id}/audit-runs",
    response_model=AuditRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audit_run(
    workspace_id: uuid.UUID,
    payload: AuditRunCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> AuditRunView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_audit_run(membership.role)
    try:
        run = await audit_service.create_run(
            session,
            workspace_id=workspace_id,
            requested_by_user_id=context.user.id,
            taxonomy_version=payload.taxonomy_version,
            mode=payload.mode,
        )
    except AuditRunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuditConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.audit_queued",
            entity_type="audit_run",
            entity_id=run.id,
            payload={
                "taxonomy_version": run.taxonomy_version,
                "mode": run.mode,
                "rule_version_count": len(run.rule_version_set),
            },
        )
    )
    await session.commit()
    try:
        celery_app.send_task("catora.audit.run", args=[str(run.id)])
    except Exception as exc:
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.failure_summary = {
            "error_type": type(exc).__name__,
            "error_message": "Unable to enqueue audit run",
        }
        await session.commit()
        raise HTTPException(status_code=503, detail="Unable to enqueue audit run") from exc
    await session.refresh(run)
    return _run_view(run)


@router.get(
    "/workspaces/{workspace_id}/audit-runs",
    response_model=list[AuditRunView],
)
async def list_audit_runs(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditRunView]:
    await auth_service.membership(session, context.user.id, workspace_id)
    runs = (
        await session.scalars(
            select(AuditRun)
            .where(AuditRun.workspace_id == workspace_id)
            .order_by(AuditRun.created_at.desc(), AuditRun.id.desc())
            .limit(limit)
        )
    ).all()
    return [_run_view(run) for run in runs]


@router.get(
    "/workspaces/{workspace_id}/audit-runs/{run_id}",
    response_model=AuditRunView,
)
async def get_audit_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> AuditRunView:
    await auth_service.membership(session, context.user.id, workspace_id)
    run = await session.scalar(
        select(AuditRun).where(
            AuditRun.id == run_id,
            AuditRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Audit run not found")
    return _run_view(run)


@router.post(
    "/workspaces/{workspace_id}/audit-runs/{run_id}/cancel",
    response_model=AuditRunView,
)
async def cancel_audit_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> AuditRunView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    _require_audit_run(membership.role)
    try:
        run = await audit_service.request_cancellation(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
        )
    except AuditRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuditRunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="catalog.audit_cancellation_requested",
            entity_type="audit_run",
            entity_id=run.id,
            payload={"status": run.status},
        )
    )
    await session.commit()
    await session.refresh(run)
    return _run_view(run)


@router.get(
    "/workspaces/{workspace_id}/audit-runs/{run_id}/findings",
    response_model=list[AuditFindingView],
)
async def list_audit_findings(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    finding_status: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    business_impact: str | None = Query(default=None),
    product_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditFindingView]:
    await auth_service.membership(session, context.user.id, workspace_id)
    run_exists = await session.scalar(
        select(AuditRun.id).where(
            AuditRun.id == run_id,
            AuditRun.workspace_id == workspace_id,
        )
    )
    if run_exists is None:
        raise HTTPException(status_code=404, detail="Audit run not found")

    query = select(AuditFinding).where(
        AuditFinding.workspace_id == workspace_id,
        AuditFinding.audit_run_id == run_id,
    )
    if finding_status is not None:
        query = query.where(AuditFinding.status == finding_status)
    if severity is not None:
        query = query.where(AuditFinding.severity == severity)
    if business_impact is not None:
        query = query.where(AuditFinding.business_impact == business_impact)
    if product_id is not None:
        query = query.where(AuditFinding.product_id == product_id)
    findings = (
        await session.scalars(
            query.order_by(
                AuditFinding.severity,
                AuditFinding.product_id,
                AuditFinding.fingerprint,
            ).limit(limit)
        )
    ).all()
    return [AuditFindingView.model_validate(finding) for finding in findings]
