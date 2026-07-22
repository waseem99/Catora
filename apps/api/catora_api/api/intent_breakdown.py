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
    IntentCoverageByIntentReport,
    IntentCoverageByIntentService,
    IntentCoverageMember,
    IntentCoverageMemberDelta,
)
from catora_api.schemas.intent_breakdown import (
    IntentCoverageByIntentResponse,
    IntentCoverageMemberDeltaView,
    IntentCoverageMemberSummaryView,
    IntentCoverageMemberView,
)
from catora_api.schemas.intents import BuyerIntentSource

router = APIRouter(tags=["buyer intent coverage"])
intent_coverage_service = IntentCoverageByIntentService()


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{run_id}/coverage/intents",
    response_model=IntentCoverageByIntentResponse,
)
async def get_intent_coverage_by_intent(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentCoverageByIntentResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        report = await intent_coverage_service.report(
            session,
            workspace_id=workspace_id,
            suite_run_id=run_id,
        )
    except IntentCoverageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentCoverageStateError, IntentCoverageDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _report_view(report)


def _report_view(
    report: IntentCoverageByIntentReport,
) -> IntentCoverageByIntentResponse:
    return IntentCoverageByIntentResponse(
        suite_run_id=report.run.id,
        source_snapshot_hash=cast(str, report.run.source_snapshot_hash),
        previous_suite_run_id=report.run.previous_run_id,
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
