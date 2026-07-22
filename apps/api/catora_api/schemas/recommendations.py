from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from catora_api.enrichment.types import (
    BrandControls,
    ConfidenceBand,
    EnrichmentRequest,
    EnrichmentTask,
    FieldKey,
    SourceDocument,
)


class RecommendationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    audit_finding_id: uuid.UUID | None = None
    task_type: EnrichmentTask
    allowed_fields: tuple[FieldKey, ...] = Field(min_length=1, max_length=200)
    original_values: dict[FieldKey, object] = Field(default_factory=dict)
    sources: tuple[SourceDocument, ...] = Field(min_length=1, max_length=200)
    brand_controls: BrandControls = Field(default_factory=BrandControls)
    budget_microunits: int | None = Field(default=None, ge=1)

    @field_validator("allowed_fields")
    @classmethod
    def reject_duplicate_allowed_fields(
        cls,
        value: tuple[FieldKey, ...],
    ) -> tuple[FieldKey, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_fields must be unique")
        return value

    def enrichment_request(self, workspace_id: uuid.UUID) -> EnrichmentRequest:
        return EnrichmentRequest(
            workspace_id=workspace_id,
            product_id=self.product_id,
            variant_id=self.variant_id,
            task_type=self.task_type,
            allowed_fields=self.allowed_fields,
            original_values=self.original_values,
            sources=self.sources,
            brand_controls=self.brand_controls,
        )


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
