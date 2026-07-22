from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, status

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models.intents import BuyerIntent, IntentProductMatch, IntentRun
from catora_api.db.models.reporting import AuditEvent
from catora_api.intents.execution import (
    IntentMatchPage,
    IntentRunDataError,
    IntentRunNotFoundError,
    IntentRunService,
    IntentRunSummary,
    IntentRunTargetError,
)
from catora_api.intents.types import IntentMatchResult, IntentMatchStatus
from catora_api.schemas.intent_runs import (
    IntentProductMatchListResponse,
    IntentProductMatchView,
    IntentRunCreateRequest,
    IntentRunStatus,
    IntentRunSummaryView,
    IntentRunView,
)

router = APIRouter(prefix="/api/v1", tags=["buyer intent runs"])
run_service = IntentRunService()


@router.post(
    "/workspaces/{workspace_id}/buyer-intents/{lineage_id}/runs",
    response_model=IntentRunView,
    status_code=status.HTTP_201_CREATED,
)
async def create_intent_run(
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    payload: IntentRunCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IntentRunView:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "analysis.run"):
        raise AuthorizationError("Buyer intent execution permission required")
    try:
        persisted = await run_service.execute(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            intent_version=payload.intent_version,
            product_ids=payload.product_ids,
        )
    except (IntentRunNotFoundError, IntentRunTargetError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntentRunDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    summary = persisted.summary
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent.run_completed",
            entity_type="intent_run",
            entity_id=persisted.run.id,
            payload={
                "lineage_id": str(persisted.intent.lineage_id),
                "intent_version": persisted.intent.version,
                "source_snapshot_hash": persisted.run.source_snapshot_hash,
                "target_count": summary.target_count,
                "product_count": summary.product_count,
                "confident_match_count": summary.confident_match_count,
                "possible_match_missing_data_count": (
                    summary.possible_match_missing_data_count
                ),
                "non_match_count": summary.non_match_count,
                "insufficient_category_data_count": (
                    summary.insufficient_category_data_count
                ),
            },
        )
    )
    await session.commit()
    await session.refresh(persisted.run)
    return _run_view(persisted.run, persisted.intent, summary)


@router.get(
    "/workspaces/{workspace_id}/intent-runs/{run_id}",
    response_model=IntentRunView,
)
async def get_intent_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentRunView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        run, intent, summary = await run_service.get(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
        )
    except IntentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run_view(run, intent, summary)


@router.get(
    "/workspaces/{workspace_id}/intent-runs/{run_id}/matches",
    response_model=IntentProductMatchListResponse,
)
async def list_intent_run_matches(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    match_status: Annotated[
        IntentMatchStatus | None,
        Query(alias="status"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> IntentProductMatchListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        page = await run_service.list_matches(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            match_status=match_status,
            offset=offset,
            limit=limit,
        )
    except IntentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _match_list_view(page, offset=offset, limit=limit)


def _run_view(
    run: IntentRun,
    intent: BuyerIntent,
    summary: IntentRunSummary,
) -> IntentRunView:
    return IntentRunView(
        id=run.id,
        workspace_id=cast(uuid.UUID, run.workspace_id),
        buyer_intent_id=run.buyer_intent_id,
        intent_lineage_id=intent.lineage_id,
        intent_version=intent.version,
        status=cast(IntentRunStatus, run.status),
        source_snapshot_hash=run.source_snapshot_hash,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        summary=IntentRunSummaryView(
            target_count=summary.target_count,
            product_count=summary.product_count,
            confident_match_count=summary.confident_match_count,
            possible_match_missing_data_count=(
                summary.possible_match_missing_data_count
            ),
            non_match_count=summary.non_match_count,
            insufficient_category_data_count=(
                summary.insufficient_category_data_count
            ),
        ),
    )


def _match_list_view(
    page: IntentMatchPage,
    *,
    offset: int,
    limit: int,
) -> IntentProductMatchListResponse:
    return IntentProductMatchListResponse(
        items=[_match_view(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


def _match_view(match: IntentProductMatch) -> IntentProductMatchView:
    score = Decimal(match.score or 0)
    return IntentProductMatchView(
        id=match.id,
        workspace_id=cast(uuid.UUID, match.workspace_id),
        intent_run_id=match.intent_run_id,
        product_id=match.product_id,
        variant_id=match.variant_id,
        status=cast(IntentMatchStatus, match.status),
        soft_score_basis_points=int(score * Decimal(10_000)),
        explanation=IntentMatchResult.model_validate(match.explanation),
        created_at=match.created_at,
    )
