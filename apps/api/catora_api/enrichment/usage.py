from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.workflow import Recommendation, RecommendationJob


@dataclass(frozen=True, slots=True)
class RecommendationUsageRecord:
    provider: str
    model: str
    cost_microunits: int
    execution_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class RecommendationUsageProvider:
    provider: str
    model: str
    recommendation_count: int
    input_tokens: int
    output_tokens: int
    cost_microunits: int


@dataclass(frozen=True, slots=True)
class RecommendationUsageSummary:
    recommendation_count: int
    completed_job_count: int
    input_tokens: int
    output_tokens: int
    cost_microunits: int
    providers: tuple[RecommendationUsageProvider, ...]


class RecommendationUsageService:
    async def summarize(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID | None = None,
        provider: str | None = None,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
    ) -> RecommendationUsageSummary:
        usage_query = _usage_query(
            workspace_id=workspace_id,
            product_id=product_id,
            provider=provider,
            created_from=created_from,
            created_before=created_before,
        )
        rows = (await session.execute(usage_query)).tuples().all()
        records = tuple(
            RecommendationUsageRecord(
                provider=model_provider,
                model=model_name,
                cost_microunits=cost_microunits,
                execution_metadata=execution_metadata,
            )
            for model_provider, model_name, cost_microunits, execution_metadata in rows
        )
        completed_job_count = int(
            (
                await session.scalar(
                    _completed_job_count_query(
                        workspace_id=workspace_id,
                        product_id=product_id,
                        provider=provider,
                        created_from=created_from,
                        created_before=created_before,
                    )
                )
            )
            or 0
        )
        return aggregate_usage(records, completed_job_count=completed_job_count)


def aggregate_usage(
    records: tuple[RecommendationUsageRecord, ...],
    *,
    completed_job_count: int,
) -> RecommendationUsageSummary:
    grouped: dict[tuple[str, str], list[int]] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0

    for record in records:
        input_tokens = _nonnegative_int(record.execution_metadata.get("input_tokens"))
        output_tokens = _nonnegative_int(record.execution_metadata.get("output_tokens"))
        cost = _nonnegative_int(record.cost_microunits)
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cost += cost
        bucket = grouped.setdefault((record.provider, record.model), [0, 0, 0, 0])
        bucket[0] += 1
        bucket[1] += input_tokens
        bucket[2] += output_tokens
        bucket[3] += cost

    providers = tuple(
        RecommendationUsageProvider(
            provider=provider,
            model=model,
            recommendation_count=values[0],
            input_tokens=values[1],
            output_tokens=values[2],
            cost_microunits=values[3],
        )
        for (provider, model), values in sorted(grouped.items())
    )
    return RecommendationUsageSummary(
        recommendation_count=len(records),
        completed_job_count=max(0, completed_job_count),
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        cost_microunits=total_cost,
        providers=providers,
    )


def _usage_query(
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID | None,
    provider: str | None,
    created_from: datetime | None,
    created_before: datetime | None,
) -> Select[tuple[str, str, int, dict[str, object]]]:
    query = select(
        Recommendation.model_provider,
        Recommendation.model_name,
        Recommendation.cost_microunits,
        Recommendation.execution_metadata,
    ).where(Recommendation.workspace_id == workspace_id)
    return _apply_recommendation_filters(
        query,
        product_id=product_id,
        provider=provider,
        created_from=created_from,
        created_before=created_before,
    )


def _completed_job_count_query(
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID | None,
    provider: str | None,
    created_from: datetime | None,
    created_before: datetime | None,
) -> Select[tuple[int]]:
    query = (
        select(func.count())
        .select_from(RecommendationJob)
        .join(
            Recommendation,
            Recommendation.id == RecommendationJob.recommendation_id,
        )
        .where(
            RecommendationJob.workspace_id == workspace_id,
            RecommendationJob.status == "completed",
            Recommendation.workspace_id == workspace_id,
        )
    )
    return _apply_recommendation_filters(
        query,
        product_id=product_id,
        provider=provider,
        created_from=created_from,
        created_before=created_before,
    )


def _apply_recommendation_filters(
    query: Select[Any],
    *,
    product_id: uuid.UUID | None,
    provider: str | None,
    created_from: datetime | None,
    created_before: datetime | None,
) -> Select[Any]:
    if product_id is not None:
        query = query.where(Recommendation.product_id == product_id)
    if provider is not None:
        query = query.where(Recommendation.model_provider == provider)
    if created_from is not None:
        query = query.where(Recommendation.created_at >= created_from)
    if created_before is not None:
        query = query.where(Recommendation.created_at < created_before)
    return query


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
