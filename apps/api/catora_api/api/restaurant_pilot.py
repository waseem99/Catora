from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
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
from catora_api.db.models.restaurant_pilot import (
    RestaurantPilotAcceptanceCheckRecord,
    RestaurantPilotAcceptanceDecisionRecord,
    RestaurantPilotAcceptancePlanRecord,
    RestaurantPilotDisconnectRunRecord,
)
from catora_api.restaurant_pilot.models import (
    PilotAcceptanceCheck,
    PilotAcceptanceDecision,
    PilotDisconnectRun,
    RestaurantPilotPlan,
)
from catora_api.restaurant_pilot.service import (
    RestaurantPilotService,
    RestaurantPilotServiceError,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/restaurant-pilots",
    tags=["restaurant pilot acceptance"],
)


def _require_enabled() -> None:
    if not get_settings().restaurant_pilot_acceptance_enabled:
        raise HTTPException(status_code=503, detail="Restaurant pilot acceptance is disabled")


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


def _require_writer(role: str) -> None:
    if not can(Role(role), "recommendations.write"):
        raise AuthorizationError("Restaurant pilot acceptance permission required")


@router.put("/plans/{pilot_key}")
async def upsert_restaurant_pilot_plan(
    workspace_id: uuid.UUID,
    pilot_key: str,
    payload: RestaurantPilotPlan,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    if payload.pilot_key != pilot_key:
        raise HTTPException(status_code=409, detail="Pilot path and payload differ")
    try:
        row = await RestaurantPilotService().upsert_plan(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            plan=payload,
        )
    except RestaurantPilotServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _plan_response(row)


@router.get("/plans")
async def list_restaurant_pilot_plans(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(RestaurantPilotAcceptancePlanRecord)
            .where(RestaurantPilotAcceptancePlanRecord.workspace_id == workspace_id)
            .order_by(RestaurantPilotAcceptancePlanRecord.submitted_at.desc())
        )
    ).all()
    return [_plan_response(row) for row in rows]


@router.get("/plans/{plan_id}")
async def get_restaurant_pilot_plan(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    row = await session.scalar(
        select(RestaurantPilotAcceptancePlanRecord).where(
            RestaurantPilotAcceptancePlanRecord.workspace_id == workspace_id,
            RestaurantPilotAcceptancePlanRecord.id == plan_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Restaurant pilot plan not found")
    return _plan_response(row)


@router.put("/plans/{plan_id}/checks/{check_key}")
async def upsert_restaurant_pilot_check(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    check_key: str,
    payload: PilotAcceptanceCheck,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    if payload.check_key != check_key:
        raise HTTPException(status_code=409, detail="Check path and payload differ")
    try:
        row = await RestaurantPilotService().upsert_check(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            actor_user_id=context.user.id,
            check=payload,
        )
    except RestaurantPilotServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _check_response(row)


@router.get("/plans/{plan_id}/checks")
async def list_restaurant_pilot_checks(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(RestaurantPilotAcceptanceCheckRecord)
            .where(
                RestaurantPilotAcceptanceCheckRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptanceCheckRecord.plan_id == plan_id,
            )
            .order_by(RestaurantPilotAcceptanceCheckRecord.check_key)
        )
    ).all()
    return [_check_response(row) for row in rows]


@router.get("/plans/{plan_id}/readiness")
async def get_restaurant_pilot_readiness(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> dict[str, object]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    try:
        readiness = await RestaurantPilotService().readiness(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
        )
    except RestaurantPilotServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return readiness.model_dump(mode="json")


@router.post(
    "/plans/{plan_id}/decisions",
    status_code=status.HTTP_201_CREATED,
)
async def record_restaurant_pilot_decision(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PilotAcceptanceDecision,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await RestaurantPilotService().record_decision(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            actor_user_id=context.user.id,
            decision=payload,
        )
    except RestaurantPilotServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _decision_response(row)


@router.get("/plans/{plan_id}/decisions")
async def list_restaurant_pilot_decisions(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(RestaurantPilotAcceptanceDecisionRecord)
            .where(
                RestaurantPilotAcceptanceDecisionRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptanceDecisionRecord.plan_id == plan_id,
            )
            .order_by(RestaurantPilotAcceptanceDecisionRecord.decided_at)
        )
    ).all()
    return [_decision_response(row) for row in rows]


@router.post(
    "/plans/{plan_id}/disconnect-runs",
    status_code=status.HTTP_201_CREATED,
)
async def record_restaurant_pilot_disconnect_run(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PilotDisconnectRun,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> dict[str, object]:
    _require_enabled()
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    _require_writer(role)
    try:
        row = await RestaurantPilotService().record_disconnect_run(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            actor_user_id=context.user.id,
            run=payload,
        )
    except RestaurantPilotServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _disconnect_response(row)


@router.get("/plans/{plan_id}/disconnect-runs")
async def list_restaurant_pilot_disconnect_runs(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> list[dict[str, object]]:
    _require_enabled()
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    rows = (
        await session.scalars(
            select(RestaurantPilotDisconnectRunRecord)
            .where(
                RestaurantPilotDisconnectRunRecord.workspace_id == workspace_id,
                RestaurantPilotDisconnectRunRecord.plan_id == plan_id,
            )
            .order_by(RestaurantPilotDisconnectRunRecord.started_at.desc())
        )
    ).all()
    return [_disconnect_response(row) for row in rows]


def _plan_response(row: RestaurantPilotAcceptancePlanRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "pilot_key": row.pilot_key,
        "client_reference": row.client_reference,
        "environment": row.environment,
        "contract_version": row.contract_version,
        "release_revision": row.release_revision,
        "plan_sha256": row.plan_sha256,
        "state": row.state,
        "submitted_at": row.submitted_at.isoformat(),
        "live_activation_allowed": False,
        "live_activation_performed": False,
    }


def _check_response(row: RestaurantPilotAcceptanceCheckRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id),
        "check_key": row.check_key,
        "category": row.category,
        "state": row.state,
        "evidence_reference": row.evidence_reference,
        "evidence_sha256": row.evidence_sha256,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "reviewer_role": row.reviewer_role,
        "reviewer_reference": row.reviewer_reference,
        "details": row.details,
    }


def _decision_response(
    row: RestaurantPilotAcceptanceDecisionRecord,
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id),
        "decision": row.decision,
        "repository_readiness_sha256": row.repository_readiness_sha256,
        "external_authorization_reference": row.external_authorization_reference,
        "external_authorization_sha256": row.external_authorization_sha256,
        "decision_note": row.decision_note,
        "decided_at": row.decided_at.isoformat(),
        "live_activation_allowed": False,
        "live_activation_performed": False,
    }


def _disconnect_response(
    row: RestaurantPilotDisconnectRunRecord,
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id),
        "idempotency_key": row.idempotency_key,
        "state": row.state,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "evidence_reference": row.evidence_reference,
        "evidence_sha256": row.evidence_sha256,
        "ordering_impact_observed": False,
        "deployment_impact_observed": False,
        "source_access_revoked": row.source_access_revoked,
        "provider_access_revoked": row.provider_access_revoked,
        "summary": row.summary,
    }
