from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, HTTPException

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
from catora_api.intents.intent_breakdown import (
    IntentCoverageMember,
    IntentCoverageMemberDelta,
)
from catora_api.intents.intent_comparisons import (
    IntentCoverageByIntentComparisonReport,
    IntentCoverageByIntentComparisonService,
)
from catora_api.schemas.intent_breakdown import (
    IntentCoverageMemberDeltaView,
    IntentCoverageMemberSummaryView,
    IntentCoverageMemberView,
)
from catora_api.schemas.intent_comparisons import (
    IntentCoverageByIntentComparisonResponse,
)
from catora_api.schemas.intents import BuyerIntentSource

router = APIRouter(tags=["buyer intent coverage"])
comparison_service = IntentCoverageByIntentComparisonService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
    "compare/{baseline_run_id}/coverage/intents",
    response_model=IntentCoverageByIntentComparisonResponse,
)
async def compare_intent_coverage_by_intent(
    workspace_id: uuid.UUID,
    selected_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentCoverageByIntentComparisonResponse:
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
    report: IntentCoverageByIntentComparisonReport,
) -> IntentCoverageByIntentComparisonResponse:
    return IntentCoverageByIntentComparisonResponse(
        selected_suite_run_id=report.selected_run.id,
        baseline_suite_run_id=report.baseline_run.id,
        selected_source_snapshot_hash=cast(
            str,
            report.selected_run.source_snapshot_hash,
        ),
        baseline_source_snapshot_hash=cast(
            str,
            report.baseline_run.source_snapshot_hash,
        ),
        selection_changed=report.selection_changed,
        items=[_member_view(item) for item in report.items],
        total=len(report.items),
    )


def _member_view(item: IntentCoverageMember) -> IntentCoverageMemberView:
    summary = item.summary
    return IntentCoverageMemberView(
        position=item.member.position,
        buyer_intent_id=item.intent.id,
        lineage_id=item.intent.lineage_id,
        intent_version=item.intent.version,
        name=item.intent.name,
        source=cast(BuyerIntentSource, item.intent.source),
        category_keys=item.category_keys,
        intent_run_id=item.intent_run.id,
        source_snapshot_hash=item.intent_run.source_snapshot_hash,
        summary=IntentCoverageMemberSummaryView(
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
            confident_coverage_basis_points=(
                summary.confident_coverage_basis_points
            ),
        ),
        delta=_delta_view(item.delta),
    )


def _delta_view(
    delta: IntentCoverageMemberDelta | None,
) -> IntentCoverageMemberDeltaView | None:
    if delta is None:
        return None
    return IntentCoverageMemberDeltaView(
        previous_intent_run_id=delta.previous_intent_run_id,
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
