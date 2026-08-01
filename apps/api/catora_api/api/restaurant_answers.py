from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
    SettingsDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.restaurant_answers.evaluator import restaurant_question_suite
from catora_api.restaurant_answers.models import (
    RestaurantAnswerRunSnapshot,
    RestaurantEntityType,
    RestaurantFactEvidence,
    RestaurantQuestionSuite,
)
from catora_api.restaurant_answers.service import (
    RestaurantAnswerEvaluationError,
    RestaurantAnswerEvaluationService,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/restaurant-answer-evaluations",
    tags=["restaurant answer evaluation"],
)


class RestaurantAnswerApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RestaurantAnswerRunRequest(RestaurantAnswerApiModel):
    entity_type: RestaurantEntityType
    entity_id: uuid.UUID
    evidence: tuple[RestaurantFactEvidence, ...] = Field(max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=160)
    as_of: datetime | None = None


class RestaurantAnswerRunResponse(RestaurantAnswerApiModel):
    run_id: uuid.UUID
    snapshot: RestaurantAnswerRunSnapshot


def _require_enabled(settings: SettingsDependency) -> None:
    if not settings.restaurant_domain_enabled:
        raise HTTPException(status_code=503, detail="Restaurant domain is disabled")
    if not settings.restaurant_answer_evaluation_enabled:
        raise HTTPException(
            status_code=503,
            detail="Restaurant answer evaluation is disabled",
        )


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


@router.get("/suite", response_model=RestaurantQuestionSuite)
async def get_restaurant_answer_suite(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> RestaurantQuestionSuite:
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    return restaurant_question_suite()


@router.post("/runs", response_model=RestaurantAnswerRunResponse)
async def run_restaurant_answer_evaluation(
    workspace_id: uuid.UUID,
    payload: RestaurantAnswerRunRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> RestaurantAnswerRunResponse:
    _require_enabled(settings)
    role = await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    if not can(Role(role), "analysis.run"):
        raise AuthorizationError("Restaurant answer evaluation permission required")
    try:
        run, snapshot = await RestaurantAnswerEvaluationService().run(
            session,
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            evidence=payload.evidence,
            idempotency_key=payload.idempotency_key,
            as_of=payload.as_of,
        )
    except RestaurantAnswerEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RestaurantAnswerRunResponse(run_id=run.id, snapshot=snapshot)


@router.get("/runs/{run_id}", response_model=RestaurantAnswerRunResponse)
async def get_restaurant_answer_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> RestaurantAnswerRunResponse:
    await _role(
        workspace_id=workspace_id,
        session=session,
        auth_service=auth_service,
        context=context,
    )
    try:
        snapshot = await RestaurantAnswerEvaluationService().snapshot(
            session,
            workspace_id,
            run_id,
        )
    except RestaurantAnswerEvaluationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = await session.get(
        __import__(
            "catora_api.db.models.restaurant_answers",
            fromlist=["RestaurantAnswerRun"],
        ).RestaurantAnswerRun,
        run_id,
    )
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Restaurant answer run not found")
    return RestaurantAnswerRunResponse(run_id=run.id, snapshot=snapshot)
