from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from catora_api.api.intent_suites import _run_view
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
from catora_api.intents.suites import IntentSuiteMemberError, IntentSuiteNotFoundError
from catora_api.schemas.intent_suite_reruns import (
    IntentSuiteHistoryRerunRequest,
    IntentSuiteHistoryRerunView,
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
