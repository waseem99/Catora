from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intent_suites import (
    IntentSuiteRunStatus,
    IntentSuiteRunSummaryView,
)


class IntentSuiteRunHistoryItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    intent_suite_id: uuid.UUID
    previous_run_id: uuid.UUID | None
    status: IntentSuiteRunStatus
    requested_product_ids: tuple[uuid.UUID, ...]
    source_snapshot_hash: str | None = Field(default=None, min_length=64, max_length=64)
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    summary: IntentSuiteRunSummaryView


class IntentSuiteRunHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IntentSuiteRunHistoryItemView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
