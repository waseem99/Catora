from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ValueState = Literal[
    "present",
    "missing",
    "unknown",
    "not_applicable",
    "conflicting",
]
Confidence = Literal["high", "medium", "low"]
type JsonValue = dict[str, object] | list[object] | str | int | float | bool | None


class CatalogReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ProductAttributeView(CatalogReadModel):
    id: uuid.UUID
    variant_id: uuid.UUID | None
    key: str
    value: JsonValue
    value_type: str
    unit: str | None
    locale: str | None
    value_state: ValueState
    transformer_version: str | None
    confidence: Confidence
    created_at: datetime
    updated_at: datetime


class ProductImageView(CatalogReadModel):
    id: uuid.UUID
    variant_id: uuid.UUID | None
    url: str
    alt_text: str | None
    position: int
    checksum: str | None
    created_at: datetime
    updated_at: datetime


class ProductVariantView(CatalogReadModel):
    id: uuid.UUID
    canonical_key: str
    sku: str | None
    title: str | None
    option_values: dict[str, object]
    is_retired: bool
    attributes: list[ProductAttributeView]
    images: list[ProductImageView]
    created_at: datetime
    updated_at: datetime


class ProductListItem(CatalogReadModel):
    id: uuid.UUID
    canonical_key: str
    title: str
    primary_category_id: uuid.UUID | None
    status: str
    variant_count: int = Field(ge=0)
    attribute_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class ProductListResponse(CatalogReadModel):
    items: list[ProductListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ProductDetailView(CatalogReadModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    canonical_key: str
    title: str
    primary_category_id: uuid.UUID | None
    status: str
    product_attributes: list[ProductAttributeView]
    product_images: list[ProductImageView]
    variants: list[ProductVariantView]
    warning_count: int = Field(ge=0)
    provenance_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class EvidenceReferenceView(CatalogReadModel):
    id: uuid.UUID
    source_record_id: uuid.UUID
    catalog_source_id: uuid.UUID
    catalog_source_name: str
    source_type: str
    external_id: str
    source_updated_at: datetime | None
    snapshot_at: datetime
    product_id: uuid.UUID | None
    variant_id: uuid.UUID | None
    attribute_id: uuid.UUID | None
    attribute_key: str | None
    field_path: str
    excerpt: str | None
    checksum: str
    created_at: datetime


class ProductProvenanceResponse(CatalogReadModel):
    product_id: uuid.UUID
    items: list[EvidenceReferenceView]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
