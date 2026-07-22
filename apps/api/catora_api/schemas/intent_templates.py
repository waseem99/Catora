from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from catora_api.intents.types import StructuredBuyerIntent
from catora_api.schemas.intents import BuyerIntentView


class BuyerIntentTemplateView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    key: str
    version: Literal[1]
    taxonomy_version: str
    name: str
    summary: str
    use_cases: tuple[str, ...]
    structured_intent: StructuredBuyerIntent


class BuyerIntentTemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BuyerIntentTemplateView]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class BuyerIntentTemplateMaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_template_version: int = Field(default=1, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=250)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class BuyerIntentTemplateMaterializationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str
    template_version: Literal[1]
    taxonomy_version: str
    buyer_intent: BuyerIntentView
