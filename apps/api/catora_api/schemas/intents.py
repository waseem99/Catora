from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from catora_api.intents.types import StructuredBuyerIntent

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
