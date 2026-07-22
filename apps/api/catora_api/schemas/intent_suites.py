from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

IntentSuiteRunStatus = Literal["running", "completed", "failed"]


class IntentSuiteMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lineage_id: uuid.UUID
    intent_version: int = Field(ge=1)


class IntentSuiteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=250)
    description: str | None = Field(default=None, max_length=2_000)
    members: tuple[IntentSuiteMemberRequest, ...] = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("members")
    @classmethod
    def reject_duplicate_members(
        cls,
        value: tuple[IntentSuiteMemberRequest, ...],
    ) -> tuple[IntentSuiteMemberRequest, ...]:
        keys = [(item.lineage_id, item.intent_version) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("suite members must be unique")
        return value


class IntentSuiteMemberView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0)
    buyer_intent_id: uuid.UUID
    lineage_id: uuid.UUID
    intent_version: int = Field(ge=1)
    name: str


class IntentSuiteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    members: list[IntentSuiteMemberView]
    created_at: datetime
    updated_at: datetime


class IntentSuiteListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IntentSuiteView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class IntentSuiteRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class IntentSuiteRunSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_count: int = Field(ge=0)
    intent_run_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    confident_match_count: int = Field(ge=0)
    possible_match_missing_data_count: int = Field(ge=0)
    non_match_count: int = Field(ge=0)
    insufficient_category_data_count: int = Field(ge=0)
    confident_coverage_basis_points: int = Field(ge=0, le=10_000)


class IntentSuiteRunDeltaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_run_id: uuid.UUID
    target_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


class IntentSuiteRunView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    intent_suite_id: uuid.UUID
    previous_run_id: uuid.UUID | None
    status: IntentSuiteRunStatus
    requested_product_ids: tuple[uuid.UUID, ...]
    source_snapshot_hash: str | None = Field(default=None, min_length=64, max_length=64)
    intent_run_ids: tuple[uuid.UUID, ...]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    summary: IntentSuiteRunSummaryView
    delta: IntentSuiteRunDeltaView | None
