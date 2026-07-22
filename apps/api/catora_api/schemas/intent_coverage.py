from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from catora_api.intents.types import FieldKey


class IntentCoverageTotalsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    confident_match_count: int = Field(ge=0)
    possible_match_missing_data_count: int = Field(ge=0)
    non_match_count: int = Field(ge=0)
    insufficient_category_data_count: int = Field(ge=0)
    confident_coverage_basis_points: int = Field(ge=0, le=10_000)


class IntentCategoryCoverageView(IntentCoverageTotalsView):
    model_config = ConfigDict(extra="forbid")

    category_key: str | None = Field(default=None, min_length=1, max_length=150)


class IntentCategoryCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    items: list[IntentCategoryCoverageView]
    total: int = Field(ge=0)
    totals: IntentCoverageTotalsView


class IntentRemediationPriorityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority_rank: int = Field(ge=1)
    field_key: FieldKey
    affected_intent_count: int = Field(ge=0)
    affected_target_count: int = Field(ge=0)
    affected_product_count: int = Field(ge=0)
    intent_impact_basis_points: int = Field(ge=0, le=10_000)
    target_impact_basis_points: int = Field(ge=0, le=10_000)
    product_impact_basis_points: int = Field(ge=0, le=10_000)
    missing_constraint_count: int = Field(ge=0)
    conflicting_constraint_count: int = Field(ge=0)
    category_keys: tuple[str, ...]
    unclassified_target_count: int = Field(ge=0)


class IntentRemediationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    category_bucket: str | None
    items: list[IntentRemediationPriorityView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    scope: IntentCoverageTotalsView
