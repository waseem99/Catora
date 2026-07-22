from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RecommendationCostSummary(BaseModel):
    recommendation_count: int = Field(ge=0)
    total_cost_microunits: int = Field(ge=0)


class RecommendationProviderUsage(BaseModel):
    provider_name: str
    model_name: str
    recommendation_count: int = Field(ge=0)
    total_cost_microunits: int = Field(ge=0)


class RecommendationTaskUsage(BaseModel):
    task_type: str
    recommendation_count: int = Field(ge=0)
    total_cost_microunits: int = Field(ge=0)


class RecommendationJobUsage(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    active_budget_microunits: int = Field(ge=0)


class RecommendationUsageReport(BaseModel):
    workspace_id: uuid.UUID
    created_from: datetime | None
    created_to: datetime | None
    recommendations: RecommendationCostSummary
    jobs: RecommendationJobUsage
    providers: list[RecommendationProviderUsage]
    tasks: list[RecommendationTaskUsage]
