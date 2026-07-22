from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from catora_api.enrichment.types import ConfidenceBand, EnrichmentTask


class RecommendationFieldView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recommendation_id: uuid.UUID
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=150)
    original_value: object | None
    proposed_value: object | None
    edited_value: object | None
    evidence: list[dict[str, object]]
    confidence: ConfidenceBand
    requires_verification: bool
    proposal_metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class RecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    audit_finding_id: uuid.UUID | None
    status: str = Field(min_length=1, max_length=30)
    task_type: EnrichmentTask
    model_provider: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    cost_microunits: int = Field(ge=0)
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    execution_metadata: dict[str, object]
    fields: list[RecommendationFieldView]
    created_at: datetime
    updated_at: datetime


class RecommendationListResponse(BaseModel):
    items: list[RecommendationView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
