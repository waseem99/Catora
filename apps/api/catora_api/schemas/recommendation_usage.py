from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecommendationUsageProviderView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    recommendation_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)


class RecommendationUsageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: uuid.UUID
    product_id: uuid.UUID | None
    provider: str | None
    created_from: datetime | None
    created_before: datetime | None
    recommendation_count: int = Field(ge=0)
    completed_job_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)
    providers: list[RecommendationUsageProviderView]
