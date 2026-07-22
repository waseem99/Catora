from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.suite_history import (
    IntentSuiteRunHistoryDataError,
    IntentSuiteRunHistoryRecord,
    IntentSuiteRunHistoryService,
)
from catora_api.intents.suites import IntentSuiteNotFoundError, IntentSuiteRunSummary
from catora_api.schemas.intent_suite_history import (
    IntentSuiteRunHistoryItemView,
    IntentSuiteRunHistoryResponse,
)
from catora_api.schemas.intent_suites import (
    IntentSuiteRunStatus,
    IntentSuiteRunSummaryView,
)

router = APIRouter(tags=["buyer intent suites"])
history_service = IntentSuiteRunHistoryService()


@router.get(
    "/workspaces/{workspace_id}/intent-suites/{suite_id}/runs",
    response_model=IntentSuiteRunHistoryResponse,
)
async def list_intent_suite_runs(
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    run_status: Annotated[IntentSuiteRunStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> IntentSuiteRunHistoryResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        page = await history_service.list(
            session,
            workspace_id=workspace_id,
            suite_id=suite_id,
            status=run_status,
            offset=offset,
            limit=limit,
        )
    except IntentSuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntentSuiteRunHistoryDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IntentSuiteRunHistoryResponse(
        items=[_history_view(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


def _history_view(record: IntentSuiteRunHistoryRecord) -> IntentSuiteRunHistoryItemView:
    return IntentSuiteRunHistoryItemView(
        id=record.run.id,
        workspace_id=cast(uuid.UUID, record.run.workspace_id),
        intent_suite_id=record.run.intent_suite_id,
        previous_run_id=record.run.previous_run_id,
        status=cast(IntentSuiteRunStatus, record.run.status),
        requested_product_ids=record.requested_product_ids,
        source_snapshot_hash=record.run.source_snapshot_hash,
        started_at=record.run.started_at,
        completed_at=record.run.completed_at,
        created_at=record.run.created_at,
        summary=_summary_view(record.summary),
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
