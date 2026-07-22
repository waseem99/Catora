from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.db.models.catalog import Product
from catora_api.enrichment.usage import RecommendationUsageService
from catora_api.schemas.recommendation_usage import (
    RecommendationUsageProviderView,
    RecommendationUsageView,
)

router = APIRouter(prefix="/api/v1", tags=["recommendation usage"])
usage_service = RecommendationUsageService()


@router.get(
    "/workspaces/{workspace_id}/recommendation-usage",
    response_model=RecommendationUsageView,
)
async def get_recommendation_usage(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    provider: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_before: Annotated[datetime | None, Query()] = None,
) -> RecommendationUsageView:
    await auth_service.membership(session, context.user.id, workspace_id)
    if created_from is not None and created_before is not None:
        if created_from >= created_before:
            raise HTTPException(
                status_code=422,
                detail="created_from must be earlier than created_before",
            )
    if product_id is not None:
        product_exists = await session.scalar(
            select(Product.id).where(
                Product.id == product_id,
                Product.workspace_id == workspace_id,
                Product.deleted_at.is_(None),
            )
        )
        if product_exists is None:
            raise HTTPException(status_code=404, detail="Product not found")

    summary = await usage_service.summarize(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
        provider=provider,
        created_from=created_from,
        created_before=created_before,
    )
    return RecommendationUsageView(
        workspace_id=workspace_id,
        product_id=product_id,
        provider=provider,
        created_from=created_from,
        created_before=created_before,
        recommendation_count=summary.recommendation_count,
        completed_job_count=summary.completed_job_count,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
        cost_microunits=summary.cost_microunits,
        providers=[
            RecommendationUsageProviderView(
                provider=item.provider,
                model=item.model,
                recommendation_count=item.recommendation_count,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                cost_microunits=item.cost_microunits,
            )
            for item in summary.providers
        ],
    )
