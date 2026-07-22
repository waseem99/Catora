from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageStateError,
)
from catora_api.intents.match_transitions import (
    IntentMatchEvidence,
    IntentMatchTransition,
    IntentMatchTransitionPage,
    IntentMatchTransitionService,
)
from catora_api.intents.types import IntentMatchStatus
from catora_api.schemas.match_transitions import (
    IntentMatchEvidenceView,
    IntentMatchTransitionResponse,
    IntentMatchTransitionView,
)

router = APIRouter(tags=["buyer intent coverage"])
match_transition_service = IntentMatchTransitionService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
    "compare/{baseline_run_id}/intents/{buyer_intent_id}/match-transitions",
    response_model=IntentMatchTransitionResponse,
)
async def compare_intent_match_transitions(
    workspace_id: uuid.UUID,
    selected_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    buyer_intent_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    selected_status: Annotated[IntentMatchStatus | None, Query()] = None,
    baseline_status: Annotated[IntentMatchStatus | None, Query()] = None,
    changed_only: Annotated[bool, Query()] = True,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> IntentMatchTransitionResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        page = await match_transition_service.compare(
            session,
            workspace_id=workspace_id,
            selected_suite_run_id=selected_run_id,
            baseline_suite_run_id=baseline_run_id,
            buyer_intent_id=buyer_intent_id,
            selected_status=selected_status,
            baseline_status=baseline_status,
            changed_only=changed_only,
            offset=offset,
            limit=limit,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _page_view(
        page,
        selected_status=selected_status,
        baseline_status=baseline_status,
        changed_only=changed_only,
        offset=offset,
        limit=limit,
    )


def _page_view(
    page: IntentMatchTransitionPage,
    *,
    selected_status: IntentMatchStatus | None,
    baseline_status: IntentMatchStatus | None,
    changed_only: bool,
    offset: int,
    limit: int,
) -> IntentMatchTransitionResponse:
    return IntentMatchTransitionResponse(
        selected_suite_run_id=page.selected_suite_run.id,
        baseline_suite_run_id=page.baseline_suite_run.id,
        buyer_intent_id=page.member.buyer_intent_id,
        member_position=page.member.position,
        selected_intent_run_id=page.selected_intent_run.id,
        baseline_intent_run_id=page.baseline_intent_run.id,
        selected_source_snapshot_hash=cast(
            str,
            page.selected_suite_run.source_snapshot_hash,
        ),
        baseline_source_snapshot_hash=cast(
            str,
            page.baseline_suite_run.source_snapshot_hash,
        ),
        selected_intent_snapshot_hash=page.selected_intent_run.source_snapshot_hash,
        baseline_intent_snapshot_hash=page.baseline_intent_run.source_snapshot_hash,
        selection_changed=page.selection_changed,
        selected_status_filter=selected_status,
        baseline_status_filter=baseline_status,
        changed_only=changed_only,
        items=[_transition_view(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


def _transition_view(item: IntentMatchTransition) -> IntentMatchTransitionView:
    return IntentMatchTransitionView(
        product_id=item.product_id,
        variant_id=item.variant_id,
        presence=item.presence,
        selected=_evidence_view(item.selected),
        baseline=_evidence_view(item.baseline),
        status_changed=item.status_changed,
        soft_score_basis_points_delta=item.soft_score_basis_points_delta,
        evidence_changed=item.evidence_changed,
        changed=item.changed,
    )


def _evidence_view(
    item: IntentMatchEvidence | None,
) -> IntentMatchEvidenceView | None:
    if item is None:
        return None
    return IntentMatchEvidenceView(
        match_id=item.match_id,
        intent_run_id=item.intent_run_id,
        status=item.status,
        soft_score_basis_points=item.soft_score_basis_points,
        explanation=item.explanation,
        created_at=item.created_at,
    )
