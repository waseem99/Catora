from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceType = Literal["csv"]
JobStatus = Literal[
    "queued",
    "validating",
    "running",
    "partially_completed",
    "completed",
    "failed",
    "cancelled",
]


class IngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CsvMappingRequest(IngestionModel):
    product_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    variant_id: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    product_url: str | None = Field(default=None, min_length=1, max_length=200)
    price: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, min_length=1, max_length=200)
    availability: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=200)
    image_url: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator(
        "product_id",
        "title",
        "variant_id",
        "sku",
        "description",
        "product_url",
        "price",
        "currency",
        "availability",
        "category",
        "image_url",
        mode="before",
    )
    @classmethod
    def strip_column(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CsvSourceCreateRequest(IngestionModel):
    name: str = Field(min_length=2, max_length=200)
    source_type: SourceType = "csv"
    object_key: str = Field(min_length=1, max_length=700)
    mapping: CsvMappingRequest
    encoding: str = Field(default="utf-8-sig", min_length=3, max_length=50)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)


class CsvUploadResponse(IngestionModel):
    object_key: str
    size_bytes: int
    content_type: str


class CatalogSourceView(IngestionModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    source_type: str
    status: str
    storefront_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SourceValidationResponse(IngestionModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    discovered_fields: list[str]


class IngestionJobView(IngestionModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    catalog_source_id: uuid.UUID
    status: JobStatus
    processed_count: int
    success_count: int
    rejection_count: int
    warning_count: int
    checkpoint: dict[str, object]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceRecordSample(IngestionModel):
    id: uuid.UUID
    external_id: str
    record_type: str
    payload: dict[str, object]
    content_hash: str
    source_updated_at: datetime | None
    snapshot_at: datetime
