from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.enrichment.types import EnrichmentTask
from catora_api.schemas.recommendations import (
    RecommendationFieldView,
    RecommendationListResponse,
    RecommendationView,
)

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


async def _fields_by_recommendation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    recommendation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[RecommendationField]]:
    if not recommendation_ids:
        return {}
    fields = (
        await session.scalars(
            select(RecommendationField)
            .where(
                RecommendationField.workspace_id == workspace_id,
                RecommendationField.recommendation_id.in_(recommendation_ids),
            )
            .order_by(
                RecommendationField.recommendation_id,
                RecommendationField.field_key,
                RecommendationField.id,
            )
        )
    ).all()
    grouped: defaultdict[uuid.UUID, list[RecommendationField]] = defaultdict(list)
    for field in fields:
        grouped[field.recommendation_id].append(field)
    return dict(grouped)


def _recommendation_view(
    recommendation: Recommendation,
    fields: list[RecommendationField],
) -> RecommendationView:
    return RecommendationView(
        id=recommendation.id,
        workspace_id=cast(uuid.UUID, recommendation.workspace_id),
        product_id=recommendation.product_id,
        variant_id=recommendation.variant_id,
        audit_finding_id=recommendation.audit_finding_id,
        status=recommendation.status,
        task_type=cast(EnrichmentTask, recommendation.task_type),
        model_provider=recommendation.model_provider,
        model_name=recommendation.model_name,
        prompt_version=recommendation.prompt_version,
        cost_microunits=recommendation.cost_microunits,
        source_snapshot_hash=recommendation.source_snapshot_hash,
        execution_metadata=recommendation.execution_metadata,
        fields=[RecommendationFieldView.model_validate(field) for field in fields],
        created_at=recommendation.created_at,
        updated_at=recommendation.updated_at,
    )


@router.get(
    "/workspaces/{workspace_id}/recommendations",
    response_model=RecommendationListResponse,
)
async def list_recommendations(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", min_length=1, max_length=30),
    ] = None,
    task_type: Annotated[EnrichmentTask | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RecommendationListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    query = select(Recommendation).where(Recommendation.workspace_id == workspace_id)
    if product_id is not None:
        query = query.where(Recommendation.product_id == product_id)
    if status_filter is not None:
        query = query.where(Recommendation.status == status_filter)
    if task_type is not None:
        query = query.where(Recommendation.task_type == task_type)

    total = int(
        (
            await session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
        )
        or 0
    )
    recommendations = (
        await session.scalars(
            query.order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    fields_by_recommendation = await _fields_by_recommendation(
        session,
        workspace_id=workspace_id,
        recommendation_ids=[item.id for item in recommendations],
    )
    return RecommendationListResponse(
        items=[
            _recommendation_view(item, fields_by_recommendation.get(item.id, []))
            for item in recommendations
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/workspaces/{workspace_id}/recommendations/{recommendation_id}",
    response_model=RecommendationView,
)
async def get_recommendation(
    workspace_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
) -> RecommendationView:
    await auth_service.membership(session, context.user.id, workspace_id)
    recommendation = await session.scalar(
        select(Recommendation).where(
            Recommendation.id == recommendation_id,
            Recommendation.workspace_id == workspace_id,
        )
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    fields_by_recommendation = await _fields_by_recommendation(
        session,
        workspace_id=workspace_id,
        recommendation_ids=[recommendation.id],
    )
    return _recommendation_view(
        recommendation,
        fields_by_recommendation.get(recommendation.id, []),
    )
