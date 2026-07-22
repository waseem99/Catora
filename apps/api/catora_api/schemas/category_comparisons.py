from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intent_coverage import (
    IntentCategoryCoverageView,
    IntentCoverageTotalsView,
)


class IntentCoverageDeltaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_count_delta: int
    target_count_delta: int
    product_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


class IntentCategoryCoverageComparisonItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_key: str | None = Field(default=None, min_length=1, max_length=150)
    presence: Literal["retained", "added", "removed"]
    selected: IntentCategoryCoverageView | None
    baseline: IntentCategoryCoverageView | None
    delta: IntentCoverageDeltaView


class IntentCategoryCoverageComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_suite_run_id: uuid.UUID
    baseline_suite_run_id: uuid.UUID
    selected_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    baseline_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    selection_changed: bool
    items: list[IntentCategoryCoverageComparisonItemView]
    total: int = Field(ge=0)
    selected_totals: IntentCoverageTotalsView
    baseline_totals: IntentCoverageTotalsView
    totals_delta: IntentCoverageDeltaView
