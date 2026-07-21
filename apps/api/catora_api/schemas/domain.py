from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class WorkspaceSummary(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str


class SourceCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["shopify", "csv", "sitemap", "urls"]
    storefront_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SourceSummary(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    source_type: str
    status: str


class ProductSummary(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    canonical_key: str
    title: str
    primary_category_id: uuid.UUID | None = None
    status: str


class ProductAttributeView(APIModel):
    id: uuid.UUID
    key: str
    value: Any | None
    value_type: str
    unit: str | None
    locale: str | None
    value_state: Literal["present", "missing", "unknown", "not_applicable", "conflicting"]
    confidence: Literal["high", "medium", "low"]


class FindingSummary(APIModel):
    id: uuid.UUID
    audit_run_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    severity: Literal["critical", "high", "medium", "low", "informational"]
    title: str
    business_impact: str
    status: str


class BuyerIntentCreate(APIModel):
    name: str = Field(min_length=1, max_length=250)
    query: str = Field(min_length=3)
    market: str | None = None


class IntentMatchSummary(APIModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    status: Literal[
        "confident_match",
        "possible_match_missing_data",
        "non_match",
        "insufficient_category_data",
    ]
    score: float | None
    explanation: dict[str, Any]


class RecommendationFieldView(APIModel):
    id: uuid.UUID
    field_key: str
    original_value: Any | None
    proposed_value: Any | None
    edited_value: Any | None
    evidence: list[dict[str, Any]]
    confidence: Literal["high", "medium", "low"]
    requires_verification: bool


class RecommendationView(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    status: str
    task_type: str
    model_provider: str
    model_name: str
    prompt_version: str
    fields: list[RecommendationFieldView] = Field(default_factory=list)


class ReportRequest(APIModel):
    report_type: Literal["executive_catalog_assessment", "operational_export"]
    audit_run_id: uuid.UUID
    intent_run_ids: list[uuid.UUID] = Field(default_factory=list)
    market_comparison_ids: list[uuid.UUID] = Field(default_factory=list)


class ReportJobView(APIModel):
    id: uuid.UUID
    status: str
    report_type: str
    template_version: str
    created_at: datetime


OPENAPI_EXAMPLES: dict[str, dict[str, object]] = {
    "source_create": {
        "name": "UAE Shopify catalog",
        "source_type": "shopify",
        "config": {"shop_domain": "example.myshopify.com"},
    },
    "buyer_intent_create": {
        "name": "Compact easy-care sofa",
        "query": "A three-seat sofa under 220 cm wide that is easy to clean",
        "market": "AE",
    },
}
