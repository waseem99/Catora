from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from catora_api.auditing.service import (
    ACTIVE_AUDIT_STATUSES,
    AuditConfigurationError,
    AuditRunConflictError,
    AuditRunNotFoundError,
)
from catora_api.auditing.stateful_service import StatefulAuditRunService
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
    AuditFindingListResponse,
    AuditFindingView,
    AuditRunCreateRequest,
    AuditRunView,
    FindingStatus,
    Severity,
)
from catora_api.worker import celery_app

router = APIRouter(prefix="/api/v1", tags=["catalog audits"])
audit_service = StatefulAuditRunService()


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
    except IntegrityError as exc:
        await session.rollback()
        active_run_id = await session.scalar(
            select(AuditRun.id).where(
                AuditRun.workspace_id == workspace_id,
                AuditRun.status.in_(ACTIVE_AUDIT_STATUSES),
            )
        )
        if active_run_id is not None:
            raise HTTPException(
                status_code=409,
                detail="An audit run is already active for this workspace",
            ) from exc
        raise

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
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
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
    response_model=AuditFindingListResponse,
)
async def list_audit_findings(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    finding_status: Annotated[FindingStatus | None, Query(alias="status")] = None,
    severity: Annotated[Severity | None, Query()] = None,
    category_key: Annotated[
        str | None,
        Query(pattern=r"^[a-z][a-z0-9_]*$"),
    ] = None,
    field_key: Annotated[
        str | None,
        Query(pattern=r"^[a-z][a-z0-9_]*$"),
    ] = None,
    market_code: Annotated[
        str | None,
        Query(alias="market", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,34}$"),
    ] = None,
    business_impact: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    remediation_type: Annotated[
        str | None,
        Query(pattern=r"^[a-z][a-z0-9_]*$"),
    ] = None,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AuditFindingListResponse:
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
    if category_key is not None:
        query = query.where(AuditFinding.category_key == category_key)
    if field_key is not None:
        query = query.where(AuditFinding.field_key == field_key)
    if market_code is not None:
        query = query.where(AuditFinding.market_codes.contains([market_code]))
    if business_impact is not None:
        query = query.where(AuditFinding.business_impact == business_impact)
    if remediation_type is not None:
        query = query.where(AuditFinding.remediation_type == remediation_type)
    if product_id is not None:
        query = query.where(AuditFinding.product_id == product_id)

    total = int(
        (
            await session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
        )
        or 0
    )
    severity_order = case(
        (AuditFinding.severity == "critical", 0),
        (AuditFinding.severity == "high", 1),
        (AuditFinding.severity == "medium", 2),
        (AuditFinding.severity == "low", 3),
        else_=4,
    )
    findings = (
        await session.scalars(
            query.order_by(
                severity_order,
                AuditFinding.category_key,
                AuditFinding.product_id,
                AuditFinding.field_key,
                AuditFinding.fingerprint,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return AuditFindingListResponse(
        items=[AuditFindingView.model_validate(finding) for finding in findings],
        total=total,
        offset=offset,
        limit=limit,
    )
