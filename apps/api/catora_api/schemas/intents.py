from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from catora_api.intents.types import FieldKey, StructuredBuyerIntent

BuyerIntentSource = Literal["template", "user_entered", "ai_assisted"]
BuyerIntentApprovalStatus = Literal["draft", "approved", "superseded"]


class BuyerIntentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=250)
    source: BuyerIntentSource
    structured_intent: StructuredBuyerIntent

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class BuyerIntentReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=250)
    structured_intent: StructuredBuyerIntent

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class BuyerIntentApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class BuyerIntentView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    workspace_id: uuid.UUID
    lineage_id: uuid.UUID
    supersedes_id: uuid.UUID | None
    name: str
    query: str
    structured_intent: StructuredBuyerIntent
    source: BuyerIntentSource
    version: int
    approval_status: BuyerIntentApprovalStatus
    created_at: datetime
    updated_at: datetime


class BuyerIntentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BuyerIntentView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class BuyerIntentVersionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BuyerIntentView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class BuyerIntentParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    allowed_category_keys: tuple[str, ...] = Field(default=(), max_length=100)
    allowed_field_keys: tuple[FieldKey, ...] = Field(default=(), max_length=500)
    market_id: uuid.UUID | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=35)
    budget_microunits: int | None = Field(default=None, ge=1)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized

    @field_validator("allowed_category_keys")
    @classmethod
    def normalize_category_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if any(not item for item in normalized):
            raise ValueError("allowed category keys must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed category keys must be unique")
        return normalized

    @field_validator("allowed_field_keys")
    @classmethod
    def reject_duplicate_field_keys(
        cls,
        value: tuple[FieldKey, ...],
    ) -> tuple[FieldKey, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed field keys must be unique")
        return value


class BuyerIntentParsePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_intent: StructuredBuyerIntent
    provider_name: str
    model_name: str
    prompt_version: str
    prompt_fingerprint: str = Field(min_length=64, max_length=64)
    attempt_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)
