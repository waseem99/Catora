from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catora_api.schemas.intent_suites import IntentSuiteRunView


class IntentSuiteHistoryRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_source_snapshot_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class IntentSuiteHistoryRerunView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    selection_mode: Literal["all_active", "explicit"]
    reused_product_ids: tuple[uuid.UUID, ...]
    run: IntentSuiteRunView
