from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, HTTPException, status

from catora_api.auth.dependencies import (
    AuthServiceDependency,
    CsrfContextDependency,
    SessionDependency,
)
from catora_api.auth.roles import Role, can
from catora_api.auth.service import AuthorizationError
from catora_api.db.models.reporting import AuditEvent
from catora_api.intents.execution import (
    IntentRunDataError,
    IntentRunNotFoundError,
    IntentRunTargetError,
)
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    IntentSuiteHistoryRerunNotFoundError,
    IntentSuiteHistoryRerunService,
)
from catora_api.intents.suites import (
    IntentSuiteMemberError,
    IntentSuiteNotFoundError,
    IntentSuiteRunDelta,
    IntentSuiteRunSummary,
    PersistedIntentSuiteRun,
)
from catora_api.schemas.intent_suite_reruns import (
    IntentSuiteHistoryRerunRequest,
    IntentSuiteHistoryRerunView,
)
from catora_api.schemas.intent_suites import (
    IntentSuiteRunDeltaView,
    IntentSuiteRunStatus,
    IntentSuiteRunSummaryView,
    IntentSuiteRunView,
)

router = APIRouter(tags=["buyer intent suites"])
rerun_service = IntentSuiteHistoryRerunService()


@router.post(
    "/workspaces/{workspace_id}/intent-suite-runs/{source_run_id}/rerun",
    response_model=IntentSuiteHistoryRerunView,
    status_code=status.HTTP_201_CREATED,
)
async def rerun_intent_suite_from_history(
    workspace_id: uuid.UUID,
    source_run_id: uuid.UUID,
    payload: IntentSuiteHistoryRerunRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IntentSuiteHistoryRerunView:
    await _require_suite_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        result = await rerun_service.rerun(
            session,
            workspace_id=workspace_id,
            source_run_id=source_run_id,
            expected_source_snapshot_hash=payload.expected_source_snapshot_hash,
        )
    except (
        IntentSuiteHistoryRerunNotFoundError,
        IntentSuiteNotFoundError,
        IntentRunNotFoundError,
        IntentRunTargetError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        IntentSuiteHistoryRerunConflictError,
        IntentSuiteMemberError,
        IntentRunDataError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    persisted = result.persisted
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent_suite.rerun_completed",
            entity_type="intent_suite_run",
            entity_id=persisted.run.id,
            payload={
                "intent_suite_id": str(persisted.suite.id),
                "source_run_id": str(result.source_run.id),
                "source_snapshot_hash": result.source_snapshot_hash,
                "selection_mode": result.selection_mode,
                "reused_product_count": len(result.product_ids),
                "new_source_snapshot_hash": persisted.run.source_snapshot_hash,
                "previous_run_id": (
                    str(persisted.run.previous_run_id)
                    if persisted.run.previous_run_id is not None
                    else None
                ),
                "target_count": persisted.summary.target_count,
                "confident_match_count": persisted.summary.confident_match_count,
                "confident_coverage_basis_points": (
                    persisted.summary.confident_coverage_basis_points
                ),
            },
        )
    )
    await session.commit()
    await session.refresh(persisted.run)
    return IntentSuiteHistoryRerunView(
        source_run_id=result.source_run.id,
        source_snapshot_hash=result.source_snapshot_hash,
        selection_mode=result.selection_mode,
        reused_product_ids=result.product_ids,
        run=_run_view(persisted),
    )


def _run_view(persisted: PersistedIntentSuiteRun) -> IntentSuiteRunView:
    requested = tuple(uuid.UUID(item) for item in persisted.run.requested_product_ids)
    return IntentSuiteRunView(
        id=persisted.run.id,
        workspace_id=cast(uuid.UUID, persisted.run.workspace_id),
        intent_suite_id=persisted.run.intent_suite_id,
        previous_run_id=persisted.run.previous_run_id,
        status=cast(IntentSuiteRunStatus, persisted.run.status),
        requested_product_ids=requested,
        source_snapshot_hash=persisted.run.source_snapshot_hash,
        intent_run_ids=persisted.child_run_ids,
        started_at=persisted.run.started_at,
        completed_at=persisted.run.completed_at,
        created_at=persisted.run.created_at,
        summary=_summary_view(persisted.summary),
        delta=_delta_view(persisted.delta),
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


def _delta_view(delta: IntentSuiteRunDelta | None) -> IntentSuiteRunDeltaView | None:
    if delta is None:
        return None
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


async def _require_suite_author(
    *,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    workspace_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "analysis.run"):
        raise AuthorizationError("Buyer intent suite permission required")
