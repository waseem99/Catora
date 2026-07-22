from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.intents.templates import (
    BuyerIntentTemplateNotFoundError,
    get_buyer_intent_template,
    list_buyer_intent_templates,
)
from catora_api.schemas.intent_templates import (
    BuyerIntentTemplateListResponse,
    BuyerIntentTemplateView,
)

router = APIRouter(prefix="/api/v1", tags=["buyer intent templates"])


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
