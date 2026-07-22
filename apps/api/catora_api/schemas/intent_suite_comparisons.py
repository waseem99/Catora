from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intent_suites import (
    IntentSuiteRunDeltaView,
    IntentSuiteRunSummaryView,
)


class IntentSuiteRunComparisonSideView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    requested_product_ids: tuple[uuid.UUID, ...]
    started_at: datetime
    completed_at: datetime
    created_at: datetime
    summary: IntentSuiteRunSummaryView


class IntentSuiteRunComparisonView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_suite_id: uuid.UUID
    run: IntentSuiteRunComparisonSideView
    baseline: IntentSuiteRunComparisonSideView
    selection_changed: bool
    delta: IntentSuiteRunDeltaView
