from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, HTTPException

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.suite_comparisons import (
    IntentSuiteRunComparisonConflictError,
    IntentSuiteRunComparisonService,
    IntentSuiteRunComparisonSide,
)
from catora_api.intents.suite_reruns import IntentSuiteHistoryRerunConflictError
from catora_api.intents.suites import (
    IntentSuiteNotFoundError,
    IntentSuiteRunDelta,
    IntentSuiteRunSummary,
)
from catora_api.schemas.intent_suite_comparisons import (
    IntentSuiteRunComparisonSideView,
    IntentSuiteRunComparisonView,
)
from catora_api.schemas.intent_suites import (
    IntentSuiteRunDeltaView,
    IntentSuiteRunSummaryView,
)

router = APIRouter(tags=["buyer intent suites"])
comparison_service = IntentSuiteRunComparisonService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{run_id}/compare/{baseline_run_id}",
    response_model=IntentSuiteRunComparisonView,
)
async def compare_intent_suite_runs(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentSuiteRunComparisonView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        comparison = await comparison_service.compare(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            baseline_run_id=baseline_run_id,
        )
    except IntentSuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        IntentSuiteRunComparisonConflictError,
        IntentSuiteHistoryRerunConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return IntentSuiteRunComparisonView(
        intent_suite_id=comparison.run.persisted.run.intent_suite_id,
        run=_side_view(comparison.run),
        baseline=_side_view(comparison.baseline),
        selection_changed=comparison.selection_changed,
        delta=_delta_view(comparison.delta),
    )


def _side_view(side: IntentSuiteRunComparisonSide) -> IntentSuiteRunComparisonSideView:
    run = side.persisted.run
    return IntentSuiteRunComparisonSideView(
        run_id=run.id,
        source_snapshot_hash=side.source_snapshot_hash,
        requested_product_ids=side.product_ids,
        started_at=cast(datetime, run.started_at),
        completed_at=cast(datetime, run.completed_at),
        created_at=run.created_at,
        summary=_summary_view(side.persisted.summary),
    )


def _summary_view(summary: IntentSuiteRunSummary) -> IntentSuiteRunSummaryView:
    return IntentSuiteRunSummaryView(
        member_count=summary.member_count,
        intent_run_count=summary.intent_run_count,
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
        confident_coverage_basis_points=summary.confident_coverage_basis_points,
    )


def _delta_view(delta: IntentSuiteRunDelta) -> IntentSuiteRunDeltaView:
    return IntentSuiteRunDeltaView(
        previous_run_id=delta.previous_run_id,
        target_count_delta=delta.target_count_delta,
        confident_match_count_delta=delta.confident_match_count_delta,
        possible_match_missing_data_count_delta=(
            delta.possible_match_missing_data_count_delta
        ),
        non_match_count_delta=delta.non_match_count_delta,
        insufficient_category_data_count_delta=(
            delta.insufficient_category_data_count_delta
        ),
        confident_coverage_basis_points_delta=(
            delta.confident_coverage_basis_points_delta
        ),
    )
