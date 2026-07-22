from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, HTTPException

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.category_comparisons import (
    IntentCategoryCoverageComparisonItem,
    IntentCategoryCoverageComparisonReport,
    IntentCategoryCoverageComparisonService,
    IntentCoverageDelta,
)
from catora_api.intents.coverage import (
    IntentCategoryCoverage,
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageStateError,
    IntentCoverageTotals,
)
from catora_api.schemas.category_comparisons import (
    IntentCategoryCoverageComparisonItemView,
    IntentCategoryCoverageComparisonResponse,
    IntentCoverageDeltaView,
)
from catora_api.schemas.intent_coverage import (
    IntentCategoryCoverageView,
    IntentCoverageTotalsView,
)

router = APIRouter(tags=["buyer intent coverage"])
comparison_service = IntentCategoryCoverageComparisonService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
    "compare/{baseline_run_id}/coverage/categories",
    response_model=IntentCategoryCoverageComparisonResponse,
)
async def compare_intent_category_coverage(
    workspace_id: uuid.UUID,
    selected_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentCategoryCoverageComparisonResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        report = await comparison_service.compare(
            session,
            workspace_id=workspace_id,
            selected_suite_run_id=selected_run_id,
            baseline_suite_run_id=baseline_run_id,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _comparison_view(report)


def _comparison_view(
    report: IntentCategoryCoverageComparisonReport,
) -> IntentCategoryCoverageComparisonResponse:
    return IntentCategoryCoverageComparisonResponse(
        selected_suite_run_id=report.selected.run.id,
        baseline_suite_run_id=report.baseline.run.id,
        selected_source_snapshot_hash=cast(
            str,
            report.selected.run.source_snapshot_hash,
        ),
        baseline_source_snapshot_hash=cast(
            str,
            report.baseline.run.source_snapshot_hash,
        ),
        selection_changed=report.selection_changed,
        items=[_item_view(item) for item in report.items],
        total=len(report.items),
        selected_totals=_totals_view(report.selected.totals),
        baseline_totals=_totals_view(report.baseline.totals),
        totals_delta=_delta_view(report.totals_delta),
    )


def _item_view(
    item: IntentCategoryCoverageComparisonItem,
) -> IntentCategoryCoverageComparisonItemView:
    return IntentCategoryCoverageComparisonItemView(
        category_key=item.category_key,
        presence=item.presence,
        selected=_category_view(item.selected) if item.selected is not None else None,
        baseline=_category_view(item.baseline) if item.baseline is not None else None,
        delta=_delta_view(item.delta),
    )


def _category_view(item: IntentCategoryCoverage) -> IntentCategoryCoverageView:
    return IntentCategoryCoverageView(
        category_key=item.category_key,
        intent_count=item.intent_count,
        target_count=item.target_count,
        product_count=item.product_count,
        confident_match_count=item.confident_match_count,
        possible_match_missing_data_count=(
            item.possible_match_missing_data_count
        ),
        non_match_count=item.non_match_count,
        insufficient_category_data_count=(
            item.insufficient_category_data_count
        ),
        confident_coverage_basis_points=item.confident_coverage_basis_points,
    )


def _totals_view(totals: IntentCoverageTotals) -> IntentCoverageTotalsView:
    return IntentCoverageTotalsView(
        intent_count=totals.intent_count,
        target_count=totals.target_count,
        product_count=totals.product_count,
        confident_match_count=totals.confident_match_count,
        possible_match_missing_data_count=(
            totals.possible_match_missing_data_count
        ),
        non_match_count=totals.non_match_count,
        insufficient_category_data_count=(
            totals.insufficient_category_data_count
        ),
        confident_coverage_basis_points=totals.confident_coverage_basis_points,
    )


def _delta_view(delta: IntentCoverageDelta) -> IntentCoverageDeltaView:
    return IntentCoverageDeltaView(
        intent_count_delta=delta.intent_count_delta,
        target_count_delta=delta.target_count_delta,
        product_count_delta=delta.product_count_delta,
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
