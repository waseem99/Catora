from __future__ import annotations

import uuid
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
from catora_api.db.models.reporting import AuditEvent
from catora_api.intents.execution import (
    IntentRunDataError,
    IntentRunNotFoundError,
    IntentRunTargetError,
)
from catora_api.intents.suites import (
    IntentSuiteMemberError,
    IntentSuiteNotFoundError,
    IntentSuiteRecord,
    IntentSuiteRunDelta,
    IntentSuiteRunSummary,
    IntentSuiteService,
    PersistedIntentSuiteRun,
)
from catora_api.schemas.intent_suites import (
    IntentSuiteCreateRequest,
    IntentSuiteListResponse,
    IntentSuiteMemberView,
    IntentSuiteRunCreateRequest,
    IntentSuiteRunDeltaView,
    IntentSuiteRunStatus,
    IntentSuiteRunSummaryView,
    IntentSuiteRunView,
    IntentSuiteView,
)

router = APIRouter(prefix="/api/v1", tags=["buyer intent suites"])
suite_service = IntentSuiteService()


@router.get(
    "/workspaces/{workspace_id}/intent-suites",
    response_model=IntentSuiteListResponse,
)
async def list_intent_suites(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> IntentSuiteListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    page = await suite_service.list(
        session,
        workspace_id=workspace_id,
        offset=offset,
        limit=limit,
    )
    return IntentSuiteListResponse(
        items=[_suite_view(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/workspaces/{workspace_id}/intent-suites",
    response_model=IntentSuiteView,
    status_code=status.HTTP_201_CREATED,
)
async def create_intent_suite(
    workspace_id: uuid.UUID,
    payload: IntentSuiteCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IntentSuiteView:
    await _require_suite_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        record = await suite_service.create(
            session,
            workspace_id=workspace_id,
            name=payload.name,
            description=payload.description,
            members=tuple(
                (item.lineage_id, item.intent_version) for item in payload.members
            ),
        )
    except IntentSuiteMemberError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent_suite.created",
            entity_type="intent_suite",
            entity_id=record.suite.id,
            payload={
                "member_count": len(record.members),
                "members": [
                    {
                        "lineage_id": str(item.intent.lineage_id),
                        "version": item.intent.version,
                    }
                    for item in record.members
                ],
            },
        )
    )
    await session.commit()
    await session.refresh(record.suite)
    return _suite_view(record)


@router.get(
    "/workspaces/{workspace_id}/intent-suites/{suite_id}",
    response_model=IntentSuiteView,
)
async def get_intent_suite(
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentSuiteView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        record = await suite_service.get(
            session,
            workspace_id=workspace_id,
            suite_id=suite_id,
        )
    except (IntentSuiteNotFoundError, IntentSuiteMemberError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _suite_view(record)


@router.post(
    "/workspaces/{workspace_id}/intent-suites/{suite_id}/runs",
    response_model=IntentSuiteRunView,
    status_code=status.HTTP_201_CREATED,
)
async def create_intent_suite_run(
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    payload: IntentSuiteRunCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> IntentSuiteRunView:
    await _require_suite_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        persisted = await suite_service.execute(
            session,
            workspace_id=workspace_id,
            suite_id=suite_id,
            product_ids=payload.product_ids,
        )
    except (IntentSuiteNotFoundError, IntentRunNotFoundError, IntentRunTargetError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentSuiteMemberError, IntentRunDataError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent_suite.run_completed",
            entity_type="intent_suite_run",
            entity_id=persisted.run.id,
            payload={
                "intent_suite_id": str(persisted.suite.id),
                "source_snapshot_hash": persisted.run.source_snapshot_hash,
                "member_count": persisted.summary.member_count,
                "target_count": persisted.summary.target_count,
                "confident_match_count": persisted.summary.confident_match_count,
                "confident_coverage_basis_points": (
                    persisted.summary.confident_coverage_basis_points
                ),
                "previous_run_id": (
                    str(persisted.run.previous_run_id)
                    if persisted.run.previous_run_id is not None
                    else None
                ),
            },
        )
    )
    await session.commit()
    await session.refresh(persisted.run)
    return _run_view(persisted)


@router.get(
    "/workspaces/{workspace_id}/intent-suite-runs/{run_id}",
    response_model=IntentSuiteRunView,
)
async def get_intent_suite_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> IntentSuiteRunView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        persisted = await suite_service.get_run(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
        )
    except IntentSuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run_view(persisted)


def _suite_view(record: IntentSuiteRecord) -> IntentSuiteView:
    return IntentSuiteView(
        id=record.suite.id,
        workspace_id=cast(uuid.UUID, record.suite.workspace_id),
        name=record.suite.name,
        description=record.suite.description,
        members=[
            IntentSuiteMemberView(
                position=item.member.position,
                buyer_intent_id=item.intent.id,
                lineage_id=item.intent.lineage_id,
                intent_version=item.intent.version,
                name=item.intent.name,
            )
            for item in record.members
        ],
        created_at=record.suite.created_at,
        updated_at=record.suite.updated_at,
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
