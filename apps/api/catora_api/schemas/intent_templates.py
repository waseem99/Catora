from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catora_api.intents.types import StructuredBuyerIntent


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
