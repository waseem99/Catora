from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from catora_api.intents.types import IntentMatchResult, IntentMatchStatus

IntentRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class IntentRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_version: int = Field(ge=1)
    product_ids: tuple[uuid.UUID, ...] = Field(default=(), max_length=10_000)

    @field_validator("product_ids")
    @classmethod
    def reject_duplicate_products(
        cls,
        value: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("product_ids must be unique")
        return value


class IntentRunSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    confident_match_count: int = Field(ge=0)
    possible_match_missing_data_count: int = Field(ge=0)
    non_match_count: int = Field(ge=0)
    insufficient_category_data_count: int = Field(ge=0)


class IntentRunView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    buyer_intent_id: uuid.UUID
    intent_lineage_id: uuid.UUID
    intent_version: int = Field(ge=1)
    status: IntentRunStatus
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    summary: IntentRunSummaryView


class IntentProductMatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    intent_run_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    status: IntentMatchStatus
    soft_score_basis_points: int = Field(ge=0, le=10_000)
    explanation: IntentMatchResult
    created_at: datetime


class IntentProductMatchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IntentProductMatchView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
