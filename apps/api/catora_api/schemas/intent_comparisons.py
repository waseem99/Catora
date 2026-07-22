from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intent_breakdown import IntentCoverageMemberView


class IntentCoverageByIntentComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_suite_run_id: uuid.UUID
    baseline_suite_run_id: uuid.UUID
    selected_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    baseline_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    selection_changed: bool
    items: list[IntentCoverageMemberView]
    total: int = Field(ge=0)
