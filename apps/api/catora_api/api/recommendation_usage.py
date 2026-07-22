from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.db.models.workflow import Recommendation, RecommendationJob
from catora_api.schemas.recommendation_usage import (
    RecommendationCostSummary,
    RecommendationJobUsage,
    RecommendationProviderUsage,
    RecommendationTaskUsage,
    RecommendationUsageReport,
)

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


@router.get(
    "/workspaces/{workspace_id}/recommendation-usage",
    response_model=RecommendationUsageReport,
)
async def get_recommendation_usage(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
) -> RecommendationUsageReport:
    await auth_service.membership(session, context.user.id, workspace_id)
    if created_from is not None and created_to is not None and created_to < created_from:
        raise HTTPException(status_code=422, detail="created_to must not precede created_from")

    recommendation_filters = [Recommendation.workspace_id == workspace_id]
    job_filters = [RecommendationJob.workspace_id == workspace_id]
    if created_from is not None:
        recommendation_filters.append(Recommendation.created_at >= created_from)
        job_filters.append(RecommendationJob.created_at >= created_from)
    if created_to is not None:
        recommendation_filters.append(Recommendation.created_at < created_to)
        job_filters.append(RecommendationJob.created_at < created_to)

    recommendation_count, total_cost = (
        await session.execute(
            select(
                func.count(Recommendation.id),
                func.coalesce(func.sum(Recommendation.cost_microunits), 0),
            ).where(*recommendation_filters)
        )
    ).one()

    provider_rows = (
        await session.execute(
            select(
                Recommendation.model_provider,
                Recommendation.model_name,
                func.count(Recommendation.id),
                func.coalesce(func.sum(Recommendation.cost_microunits), 0),
            )
            .where(*recommendation_filters)
            .group_by(Recommendation.model_provider, Recommendation.model_name)
            .order_by(Recommendation.model_provider, Recommendation.model_name)
        )
    ).all()

    task_rows = (
        await session.execute(
            select(
                Recommendation.task_type,
                func.count(Recommendation.id),
                func.coalesce(func.sum(Recommendation.cost_microunits), 0),
            )
            .where(*recommendation_filters)
            .group_by(Recommendation.task_type)
            .order_by(Recommendation.task_type)
        )
    ).all()

    job_rows = (
        await session.execute(
            select(
                RecommendationJob.status,
                func.count(RecommendationJob.id),
                func.coalesce(func.sum(RecommendationJob.retry_count), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                RecommendationJob.status.in_(("queued", "running")),
                                RecommendationJob.budget_microunits,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(*job_filters)
            .group_by(RecommendationJob.status)
            .order_by(RecommendationJob.status)
        )
    ).all()

    statuses = ("queued", "running", "completed", "failed", "cancelled")
    status_counts = {status: 0 for status in statuses}
    retry_count = 0
    active_budget = 0
    for status_name, count_value, retry_value, active_value in job_rows:
        status_counts[str(status_name)] = int(count_value)
        retry_count += int(retry_value)
        active_budget += int(active_value)

    return RecommendationUsageReport(
        workspace_id=workspace_id,
        created_from=created_from,
        created_to=created_to,
        recommendations=RecommendationCostSummary(
            recommendation_count=int(recommendation_count),
            total_cost_microunits=int(total_cost),
        ),
        jobs=RecommendationJobUsage(
            total=sum(status_counts.values()),
            queued=status_counts["queued"],
            running=status_counts["running"],
            completed=status_counts["completed"],
            failed=status_counts["failed"],
            cancelled=status_counts["cancelled"],
            retry_count=retry_count,
            active_budget_microunits=active_budget,
        ),
        providers=[
            RecommendationProviderUsage(
                provider_name=str(provider_name),
                model_name=str(model_name),
                recommendation_count=int(count_value),
                total_cost_microunits=int(cost_value),
            )
            for provider_name, model_name, count_value, cost_value in provider_rows
        ],
        tasks=[
            RecommendationTaskUsage(
                task_type=str(task_type),
                recommendation_count=int(count_value),
                total_cost_microunits=int(cost_value),
            )
            for task_type, count_value, cost_value in task_rows
        ],
    )
