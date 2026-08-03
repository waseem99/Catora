from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.config import get_settings
from catora_api.db.models.operations_console import (
    OperationsConsoleActionRecord,
    OperationsConsoleAlertRecord,
    OperationsConsoleExportRecord,
    OperationsConsoleSnapshotRecord,
    OperationsMonitorRunRecord,
    OperationsMonitorScheduleRecord,
)
from catora_api.operations_console.models import ExportFormat, MonitorSchedule
from catora_api.operations_console.service import (
    OperationsConsoleService,
    OperationsConsoleServiceError,
    export_bundle_from_record,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/operations-console",
    tags=["restaurant operations console"],
)


class OperationsConsoleApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateConsoleRequest(OperationsConsoleApiModel):
    brand_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None


class DecisionRequest(OperationsConsoleApiModel):
    decision: Literal["approved", "rejected", "completed", "blocked"]
    reason: str = Field(min_length=1, max_length=2_000)


class ResolveAlertRequest(OperationsConsoleApiModel):
    note: str = Field(min_length=1, max_length=2_000)


def _require_console_enabled() -> None:
    if not get_settings().restaurant_operations_console_enabled:
        raise HTTPException(status_code=503, detail="Restaurant operations console is disabled")


def _require_monitoring_enabled() -> None:
    settings = get_settings()
    if not settings.restaurant_operations_console_enabled:
        raise HTTPException(status_code=503, detail="Restaurant operations console is disabled")
    if not settings.restaurant_monitoring_enabled:
        raise HTTPException(status_code=503, detail="Restaurant monitoring is disabled")


async def _role(
    *,
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> str:
    membership = await auth_service.membership(
        session,
        context.user.id,
        workspace_id,
    )
    return membership.role


def _require_analysis(role: str) -> None:
    if not can(Role(role), "analysis.run"):
        raise AuthorizationError("Operations console analysis permission required")


def _require_writer(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Operations console workflow permission required")


@router.post("/snapshots", status_code=status.HTTP_201_CREATED)
async def generate_operations_console_snapshot(
    workspace_id: uuid.UUID,
    payload: GenerateConsoleRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_analysis(role)
    row = await OperationsConsoleService().generate(
        session,
        workspace_id=workspace_id,
        actor_user_id=context.user.id,
        brand_id=payload.brand_id,
        location_id=payload.location_id,
    )
    return _snapshot_response(row)


@router.get("/snapshots/latest")
async def get_latest_operations_console_snapshot(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    row = await session.scalar(
        select(OperationsConsoleSnapshotRecord)
        .where(OperationsConsoleSnapshotRecord.workspace_id == workspace_id)
        .order_by(
            OperationsConsoleSnapshotRecord.generated_at.desc(),
            OperationsConsoleSnapshotRecord.id.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Operations console snapshot not found")
    return _snapshot_response(row)


@router.get("/snapshots/{snapshot_id}")
async def get_operations_console_snapshot(
    workspace_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    row = await session.scalar(
        select(OperationsConsoleSnapshotRecord).where(
            OperationsConsoleSnapshotRecord.workspace_id == workspace_id,
            OperationsConsoleSnapshotRecord.id == snapshot_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Operations console snapshot not found")
    return _snapshot_response(row)


@router.post(
    "/snapshots/{snapshot_id}/exports/{export_format}",
    status_code=status.HTTP_201_CREATED,
)
async def create_operations_console_export(
    workspace_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    export_format: ExportFormat,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_analysis(role)
    try:
        row = await OperationsConsoleService().create_export(
            session,
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            actor_user_id=context.user.id,
            export_format=export_format,
        )
    except OperationsConsoleServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _export_response(row, include_payload=False)


@router.get("/exports/{export_id}")
async def get_operations_console_export(
    workspace_id: uuid.UUID,
    export_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    row = await session.scalar(
        select(OperationsConsoleExportRecord).where(
            OperationsConsoleExportRecord.workspace_id == workspace_id,
            OperationsConsoleExportRecord.id == export_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Operations console export not found")
    return _export_response(row, include_payload=True)


@router.get("/alerts")
async def list_operations_console_alerts(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    alert_status: Literal["open", "acknowledged", "resolved"] | None = Query(
        default=None,
        alias="status",
    ),
) -> list[dict[str, object]]:
    _require_console_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    statement = select(OperationsConsoleAlertRecord).where(
        OperationsConsoleAlertRecord.workspace_id == workspace_id
    )
    if alert_status is not None:
        statement = statement.where(OperationsConsoleAlertRecord.status == alert_status)
    rows = (
        await session.scalars(
            statement.order_by(
                OperationsConsoleAlertRecord.detected_at.desc(),
                OperationsConsoleAlertRecord.id.desc(),
            )
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "snapshot_id": str(row.snapshot_id),
            "alert_key": row.alert_key,
            "section_key": row.section_key,
            "severity": row.severity,
            "status": row.status,
            "title": row.title,
            "detail": row.detail,
            "evidence_references": row.evidence_references,
            "detected_at": row.detected_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_operations_console_alert(
    workspace_id: uuid.UUID,
    alert_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, str]:
    _require_console_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await OperationsConsoleService().acknowledge_alert(
            session,
            workspace_id=workspace_id,
            alert_id=alert_id,
            actor_user_id=context.user.id,
        )
    except OperationsConsoleServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": str(row.id), "status": row.status}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_operations_console_alert(
    workspace_id: uuid.UUID,
    alert_id: uuid.UUID,
    payload: ResolveAlertRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, str]:
    _require_console_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await OperationsConsoleService().resolve_alert(
            session,
            workspace_id=workspace_id,
            alert_id=alert_id,
            actor_user_id=context.user.id,
            note=payload.note,
        )
    except OperationsConsoleServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": str(row.id), "status": row.status}


@router.get("/actions")
async def list_operations_console_actions(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    action_state: Literal["proposed", "approved", "rejected", "completed", "blocked"]
    | None = Query(default=None, alias="state"),
) -> list[dict[str, object]]:
    _require_console_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    statement = select(OperationsConsoleActionRecord).where(
        OperationsConsoleActionRecord.workspace_id == workspace_id
    )
    if action_state is not None:
        statement = statement.where(OperationsConsoleActionRecord.state == action_state)
    rows = (
        await session.scalars(
            statement.order_by(OperationsConsoleActionRecord.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "action_key": row.action_key,
            "section_key": row.section_key,
            "title": row.title,
            "rationale": row.rationale,
            "owner_role": row.owner_role,
            "verification_method": row.verification_method,
            "evidence_references": row.evidence_references,
            "target_workflow": row.target_workflow,
            "state": row.state,
            "direct_mutation_allowed": False,
        }
        for row in rows
    ]


@router.post("/actions/{action_id}/decision")
async def decide_operations_console_action(
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: DecisionRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_console_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await OperationsConsoleService().decide_action(
            session,
            workspace_id=workspace_id,
            action_id=action_id,
            actor_user_id=context.user.id,
            decision=payload.decision,
            reason=payload.reason,
        )
    except OperationsConsoleServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": str(row.id), "state": row.state, "direct_mutation_allowed": False}


@router.get("/monitor-schedules")
async def list_operations_monitor_schedules(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_monitoring_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(OperationsMonitorScheduleRecord)
            .where(OperationsMonitorScheduleRecord.workspace_id == workspace_id)
            .order_by(OperationsMonitorScheduleRecord.schedule_key)
        )
    ).all()
    return [_schedule_response(row) for row in rows]


@router.put("/monitor-schedules/{schedule_key}")
async def upsert_operations_monitor_schedule(
    workspace_id: uuid.UUID,
    schedule_key: str,
    payload: MonitorSchedule,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_monitoring_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    if payload.schedule_key != schedule_key:
        raise HTTPException(status_code=409, detail="Schedule path and payload differ")
    row = await OperationsConsoleService().upsert_schedule(
        session,
        workspace_id=workspace_id,
        actor_user_id=context.user.id,
        schedule=payload,
    )
    return _schedule_response(row)


@router.post("/monitor-schedules/{schedule_id}/run")
async def run_operations_monitor_schedule(
    workspace_id: uuid.UUID,
    schedule_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_monitoring_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_analysis(role)
    try:
        row = await OperationsConsoleService().run_schedule(
            session,
            workspace_id=workspace_id,
            schedule_id=schedule_id,
            actor_user_id=context.user.id,
        )
    except OperationsConsoleServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": str(row.id),
        "status": row.status,
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "summary": row.summary,
        "notification_sent": False,
    }


@router.get("/monitor-runs")
async def list_operations_monitor_runs(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_monitoring_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(OperationsMonitorRunRecord)
            .where(OperationsMonitorRunRecord.workspace_id == workspace_id)
            .order_by(OperationsMonitorRunRecord.started_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "schedule_id": str(row.schedule_id),
            "status": row.status,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
            "summary": row.summary,
            "failure_detail": row.failure_detail,
        }
        for row in rows
    ]


def _snapshot_response(row: OperationsConsoleSnapshotRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "definition_version": row.definition_version,
        "generated_at": row.generated_at.isoformat(),
        "snapshot_sha256": row.snapshot_sha256,
        "snapshot": row.snapshot,
    }


def _export_response(
    row: OperationsConsoleExportRecord,
    *,
    include_payload: bool,
) -> dict[str, object]:
    bundle = export_bundle_from_record(row)
    response: dict[str, object] = {
        "id": str(row.id),
        "snapshot_id": str(row.snapshot_id),
        "export_format": bundle.export_format,
        "content_type": bundle.content_type,
        "schema_version": bundle.schema_version,
        "payload_sha256": bundle.payload_sha256,
        "byte_size": bundle.byte_size,
        "generated_at": bundle.generated_at.isoformat(),
        "contains_secrets": False,
        "contains_personal_data": False,
        "causal_claim_allowed": False,
        "direct_mutation_allowed": False,
    }
    if include_payload:
        response["sanitized_payload"] = bundle.sanitized_payload
    return response


def _schedule_response(row: OperationsMonitorScheduleRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "schedule_key": row.schedule_key,
        "cadence": row.cadence,
        "section_keys": row.section_keys,
        "timezone": row.timezone,
        "enabled": row.enabled,
        "next_due_at": row.next_due_at.isoformat() if row.next_due_at else None,
        "notification_channel": row.notification_channel,
        "notification_enabled": row.notification_enabled,
        "notification_sending_implemented": False,
    }
