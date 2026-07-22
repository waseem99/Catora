from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.category_comparisons import IntentCoverageDelta
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageStateError,
    IntentCoverageTotals,
    IntentRemediationPriority,
)
from catora_api.intents.remediation_comparisons import (
    IntentRemediationComparisonItem,
    IntentRemediationComparisonReport,
    IntentRemediationComparisonService,
    IntentRemediationDelta,
)
from catora_api.intents.types import FieldKey
from catora_api.schemas.category_comparisons import IntentCoverageDeltaView
from catora_api.schemas.intent_coverage import (
    IntentCoverageTotalsView,
    IntentRemediationPriorityView,
)
from catora_api.schemas.remediation_comparisons import (
    IntentRemediationComparisonItemView,
    IntentRemediationComparisonResponse,
    IntentRemediationDeltaView,
)

router = APIRouter(tags=["buyer intent coverage"])
remediation_comparison_service = IntentRemediationComparisonService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
    "compare/{baseline_run_id}/coverage/remediations",
    response_model=IntentRemediationComparisonResponse,
)
async def compare_intent_remediations(
    workspace_id: uuid.UUID,
    selected_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    category_bucket: Annotated[
        str | None,
        Query(
            pattern=r"^(_unclassified|[a-z][a-z0-9_]*)$",
            max_length=150,
        ),
    ] = None,
) -> IntentRemediationComparisonResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        report = await remediation_comparison_service.compare(
            session,
            workspace_id=workspace_id,
            selected_suite_run_id=selected_run_id,
            baseline_suite_run_id=baseline_run_id,
            category_bucket=category_bucket,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _report_view(report)


def _report_view(
    report: IntentRemediationComparisonReport,
) -> IntentRemediationComparisonResponse:
    return IntentRemediationComparisonResponse(
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
        category_bucket=report.category_bucket,
        items=[_item_view(item) for item in report.items],
        total=len(report.items),
        selected_scope=_totals_view(report.selected.scope),
        baseline_scope=_totals_view(report.baseline.scope),
        scope_delta=_coverage_delta_view(report.scope_delta),
    )


def _item_view(
    item: IntentRemediationComparisonItem,
) -> IntentRemediationComparisonItemView:
    return IntentRemediationComparisonItemView(
        field_key=cast(FieldKey, item.field_key),
        presence=item.presence,
        selected=_priority_view(item.selected),
        baseline=_priority_view(item.baseline),
        priority_rank_delta=item.priority_rank_delta,
        category_scope_changed=item.category_scope_changed,
        delta=_remediation_delta_view(item.delta),
    )


def _priority_view(
    item: IntentRemediationPriority | None,
) -> IntentRemediationPriorityView | None:
    if item is None:
        return None
    return IntentRemediationPriorityView(
        priority_rank=item.priority_rank,
        field_key=cast(FieldKey, item.field_key),
        affected_intent_count=item.affected_intent_count,
        affected_target_count=item.affected_target_count,
        affected_product_count=item.affected_product_count,
        intent_impact_basis_points=item.intent_impact_basis_points,
        target_impact_basis_points=item.target_impact_basis_points,
        product_impact_basis_points=item.product_impact_basis_points,
        missing_constraint_count=item.missing_constraint_count,
        conflicting_constraint_count=item.conflicting_constraint_count,
        category_keys=item.category_keys,
        unclassified_target_count=item.unclassified_target_count,
    )


def _remediation_delta_view(
    delta: IntentRemediationDelta,
) -> IntentRemediationDeltaView:
    return IntentRemediationDeltaView(
        affected_intent_count_delta=delta.affected_intent_count_delta,
        affected_target_count_delta=delta.affected_target_count_delta,
        affected_product_count_delta=delta.affected_product_count_delta,
        intent_impact_basis_points_delta=(
            delta.intent_impact_basis_points_delta
        ),
        target_impact_basis_points_delta=(
            delta.target_impact_basis_points_delta
        ),
        product_impact_basis_points_delta=(
            delta.product_impact_basis_points_delta
        ),
        missing_constraint_count_delta=delta.missing_constraint_count_delta,
        conflicting_constraint_count_delta=(
            delta.conflicting_constraint_count_delta
        ),
        unclassified_target_count_delta=(
            delta.unclassified_target_count_delta
        ),
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


def _coverage_delta_view(delta: IntentCoverageDelta) -> IntentCoverageDeltaView:
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
