from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catora_api.intents.types import FieldKey
from catora_api.schemas.category_comparisons import IntentCoverageDeltaView
from catora_api.schemas.intent_coverage import (
    IntentCoverageTotalsView,
    IntentRemediationPriorityView,
)


class IntentRemediationDeltaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affected_intent_count_delta: int
    affected_target_count_delta: int
    affected_product_count_delta: int
    intent_impact_basis_points_delta: int
    target_impact_basis_points_delta: int
    product_impact_basis_points_delta: int
    missing_constraint_count_delta: int
    conflicting_constraint_count_delta: int
    unclassified_target_count_delta: int


class IntentRemediationComparisonItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: FieldKey
    presence: Literal["retained", "added", "removed"]
    selected: IntentRemediationPriorityView | None
    baseline: IntentRemediationPriorityView | None
    priority_rank_delta: int | None
    category_scope_changed: bool
    delta: IntentRemediationDeltaView


class IntentRemediationComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_suite_run_id: uuid.UUID
    baseline_suite_run_id: uuid.UUID
    selected_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    baseline_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    selection_changed: bool
    category_bucket: str | None
    items: list[IntentRemediationComparisonItemView]
    total: int = Field(ge=0)
    selected_scope: IntentCoverageTotalsView
    baseline_scope: IntentCoverageTotalsView
    scope_delta: IntentCoverageDeltaView
