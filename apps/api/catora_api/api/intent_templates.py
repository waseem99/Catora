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
from catora_api.intents.service import BuyerIntentService
from catora_api.intents.templates import (
    BuyerIntentTemplateNotFoundError,
    get_buyer_intent_template,
    list_buyer_intent_templates,
)
from catora_api.schemas.intent_templates import (
    BuyerIntentTemplateListResponse,
    BuyerIntentTemplateMaterializationView,
    BuyerIntentTemplateMaterializeRequest,
    BuyerIntentTemplateView,
)
from catora_api.schemas.intents import BuyerIntentView

router = APIRouter(prefix="/api/v1", tags=["buyer intent templates"])
intent_service = BuyerIntentService()


@router.get(
    "/workspaces/{workspace_id}/buyer-intent-templates",
    response_model=BuyerIntentTemplateListResponse,
)
async def list_templates(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    category_key: Annotated[str | None, Query(min_length=1, max_length=150)] = None,
    use_case: Annotated[str | None, Query(min_length=1, max_length=150)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> BuyerIntentTemplateListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    page = list_buyer_intent_templates(
        category_key=category_key,
        use_case=use_case,
        offset=offset,
        limit=limit,
    )
    return BuyerIntentTemplateListResponse(
        items=[BuyerIntentTemplateView.model_validate(item) for item in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/workspaces/{workspace_id}/buyer-intent-templates/{template_key}",
    response_model=BuyerIntentTemplateView,
)
async def get_template(
    workspace_id: uuid.UUID,
    template_key: str,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> BuyerIntentTemplateView:
    await auth_service.membership(session, context.user.id, workspace_id)
    try:
        template = get_buyer_intent_template(template_key)
    except BuyerIntentTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BuyerIntentTemplateView.model_validate(template)


@router.post(
    "/workspaces/{workspace_id}/buyer-intent-templates/{template_key}/materialize",
    response_model=BuyerIntentTemplateMaterializationView,
    status_code=status.HTTP_201_CREATED,
)
async def materialize_template(
    workspace_id: uuid.UUID,
    template_key: str,
    payload: BuyerIntentTemplateMaterializeRequest,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
) -> BuyerIntentTemplateMaterializationView:
    await _require_template_author(
        session=session,
        auth_service=auth_service,
        context=context,
        workspace_id=workspace_id,
    )
    try:
        template = get_buyer_intent_template(template_key)
    except BuyerIntentTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload.expected_template_version != template.version:
        raise HTTPException(
            status_code=409,
            detail=(
                "Buyer intent template version changed; expected "
                f"{payload.expected_template_version}, found {template.version}"
            ),
        )

    intent = await intent_service.create(
        session,
        workspace_id=workspace_id,
        name=payload.name or template.name,
        source="template",
        structured_intent=template.structured_intent,
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=context.user.id,
            event_type="intent.created_from_template",
            entity_type="buyer_intent",
            entity_id=intent.id,
            payload={
                "lineage_id": str(intent.lineage_id),
                "version": intent.version,
                "source": intent.source,
                "template_key": template.key,
                "template_version": template.version,
                "taxonomy_version": template.taxonomy_version,
            },
        )
    )
    await session.commit()
    await session.refresh(intent)
    return BuyerIntentTemplateMaterializationView(
        template_key=template.key,
        template_version=template.version,
        taxonomy_version=template.taxonomy_version,
        buyer_intent=BuyerIntentView.model_validate(intent),
    )


async def _require_template_author(
    *,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: CsrfContextDependency,
    workspace_id: uuid.UUID,
) -> None:
    membership = await auth_service.membership(session, context.user.id, workspace_id)
    if not can(Role(membership.role), "analysis.run"):
        raise AuthorizationError("Buyer intent authoring permission required")
