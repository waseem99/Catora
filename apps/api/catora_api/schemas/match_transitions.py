from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catora_api.intents.types import IntentMatchResult, IntentMatchStatus


class IntentMatchEvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: uuid.UUID
    intent_run_id: uuid.UUID
    status: IntentMatchStatus
    soft_score_basis_points: int = Field(ge=0, le=10_000)
    explanation: IntentMatchResult
    created_at: datetime


class IntentMatchTransitionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    presence: Literal["retained", "added", "removed"]
    selected: IntentMatchEvidenceView | None
    baseline: IntentMatchEvidenceView | None
    status_changed: bool
    soft_score_basis_points_delta: int | None
    evidence_changed: bool
    changed: bool


class IntentMatchTransitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_suite_run_id: uuid.UUID
    baseline_suite_run_id: uuid.UUID
    buyer_intent_id: uuid.UUID
    member_position: int = Field(ge=0)
    selected_intent_run_id: uuid.UUID
    baseline_intent_run_id: uuid.UUID
    selected_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    baseline_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    selected_intent_snapshot_hash: str = Field(min_length=64, max_length=64)
    baseline_intent_snapshot_hash: str = Field(min_length=64, max_length=64)
    selection_changed: bool
    selected_status_filter: IntentMatchStatus | None
    baseline_status_filter: IntentMatchStatus | None
    changed_only: bool
    items: list[IntentMatchTransitionView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
