from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intents import BuyerIntentSource


class IntentCoverageMemberSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    confident_match_count: int = Field(ge=0)
    possible_match_missing_data_count: int = Field(ge=0)
    non_match_count: int = Field(ge=0)
    insufficient_category_data_count: int = Field(ge=0)
    confident_coverage_basis_points: int = Field(ge=0, le=10_000)


class IntentCoverageMemberDeltaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_intent_run_id: uuid.UUID
    target_count_delta: int
    product_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


class IntentCoverageMemberView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0)
    buyer_intent_id: uuid.UUID
    lineage_id: uuid.UUID
    intent_version: int = Field(ge=1)
    name: str
    source: BuyerIntentSource
    category_keys: tuple[str, ...]
    intent_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    summary: IntentCoverageMemberSummaryView
    delta: IntentCoverageMemberDeltaView | None


class IntentCoverageByIntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    previous_suite_run_id: uuid.UUID | None
    items: list[IntentCoverageMemberView]
    total: int = Field(ge=0)
