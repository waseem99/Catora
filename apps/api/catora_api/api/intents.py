from __future__ import annotations

import uuid
from typing import Annotated

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
from catora_api.intents.service import (
    BuyerIntentNotFoundError,
    BuyerIntentService,
    BuyerIntentStateError,
    BuyerIntentVersionConflictError,
)
from catora_api.schemas.intents import (
    BuyerIntentApprovalStatus,
    BuyerIntentApproveRequest,
    BuyerIntentCreateRequest,
    BuyerIntentListResponse,
    BuyerIntentReviseRequest,
    BuyerIntentSource,
    BuyerIntentVersionListResponse,
    BuyerIntentView,
)

router = APIRouter(prefix="/api/v1", tags=["buyer intents"])
intent_service = BuyerIntentService()


@router.get(
    "/workspaces/{workspace_id}/buyer-intents",
    response_model=BuyerIntentListResponse,
)
async def list_buyer_intents(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    approval_status: Annotated[BuyerIntentApprovalStatus | None, Query()] = None,
    source: Annotated[BuyerIntentSource | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> BuyerIntentListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    page = await intent_service.list_latest(
        session,
        workspace_id=workspace_id,
        approval_status=approval_status,
        source=source,
        offset=offset,
        limit=limit,
    )
    return BuyerIntentListResponse(
        items=[BuyerIntentView.model_validate(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/workspaces/{workspace_id}/buyer-intents",
    response_model=BuyerIntentView,
    status_code=status.HTTP_201_CREATED,
)
async def create_buyer_intent(
    workspace_id: uuid.UUID,
    payload: BuyerIntentCreateRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> BuyerIntentView:
    await _require_intent_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    intent = await intent_service.create(
        session,
        workspace_id=workspace_id,
        name=payload.name,
        source=payload.source,
        structured_intent=payload.structured_intent,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent.created",
            entity_type="buyer_intent",
            entity_id=intent.id,
            payload={
                "lineage_id": str(intent.lineage_id),
                "version": intent.version,
                "source": intent.source,
            },
        )
    )
    await session.commit()
    await session.refresh(intent)
    return BuyerIntentView.model_validate(intent)


@router.get(
    "/workspaces/{workspace_id}/buyer-intents/{lineage_id}",
    response_model=BuyerIntentView,
)
async def get_buyer_intent(
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> BuyerIntentView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        intent = await intent_service.latest(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
        )
    except BuyerIntentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BuyerIntentView.model_validate(intent)


@router.put(
    "/workspaces/{workspace_id}/buyer-intents/{lineage_id}",
    response_model=BuyerIntentView,
    status_code=status.HTTP_201_CREATED,
)
async def revise_buyer_intent(
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    payload: BuyerIntentReviseRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> BuyerIntentView:
    await _require_intent_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        revised = await intent_service.revise(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            expected_version=payload.expected_version,
            name=payload.name,
            structured_intent=payload.structured_intent,
        )
    except BuyerIntentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BuyerIntentVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent.revised",
            entity_type="buyer_intent",
            entity_id=revised.id,
            payload={
                "lineage_id": str(lineage_id),
                "previous_version": payload.expected_version,
                "version": revised.version,
            },
        )
    )
    await session.commit()
    await session.refresh(revised)
    return BuyerIntentView.model_validate(revised)


@router.get(
    "/workspaces/{workspace_id}/buyer-intents/{lineage_id}/versions",
    response_model=BuyerIntentVersionListResponse,
)
async def list_buyer_intent_versions(
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> BuyerIntentVersionListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        page = await intent_service.versions(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            offset=offset,
            limit=limit,
        )
    except BuyerIntentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BuyerIntentVersionListResponse(
        items=[BuyerIntentView.model_validate(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/workspaces/{workspace_id}/buyer-intents/{lineage_id}/approve",
    response_model=BuyerIntentView,
)
async def approve_buyer_intent(
    workspace_id: uuid.UUID,
    lineage_id: uuid.UUID,
    payload: BuyerIntentApproveRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> BuyerIntentView:
    await _require_intent_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        intent = await intent_service.approve(
            session,
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            expected_version=payload.expected_version,
        )
    except BuyerIntentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BuyerIntentVersionConflictError, BuyerIntentStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent.approved",
            entity_type="buyer_intent",
            entity_id=intent.id,
            payload={
                "lineage_id": str(lineage_id),
                "version": intent.version,
            },
        )
    )
    await session.commit()
    await session.refresh(intent)
    return BuyerIntentView.model_validate(intent)


async def _require_intent_author(
    *,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    workspace_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "analysis.run"):
        raise AuthorizationError("Buyer intent authoring permission required")
