from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

CATALOG_BRIDGE_PROTOCOL_VERSION = "2026-07-bridge-v1"
CATALOG_BRIDGE_MAX_BATCH_RECORDS = 250
_FORBIDDEN_FIELD = re.compile(
    r"(^|[_\-.])(customer|customers|order|orders|payment|payments|password|passwords|"
    r"session|sessions|token|tokens|address|addresses)([_\-.]|$)",
    re.IGNORECASE,
)


class CatalogBridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def _validate_catalog_value(value: JsonValue, *, depth: int = 0) -> JsonValue:
    if depth > 8:
        raise ValueError("Catalog attribute nesting cannot exceed 8 levels")
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError("Catalog attribute objects cannot exceed 500 fields")
        for key, item in value.items():
            if not key or len(key) > 160 or _FORBIDDEN_FIELD.search(key):
                raise ValueError(f"Catalog attribute key '{key}' is not allowed")
            _validate_catalog_value(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 500:
            raise ValueError("Catalog attribute arrays cannot exceed 500 items")
        for item in value:
            _validate_catalog_value(item, depth=depth + 1)
    elif isinstance(value, str) and len(value) > 20_000:
        raise ValueError("Catalog attribute strings cannot exceed 20000 characters")
    return value


class CatalogBridgeSeo(CatalogBridgeModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2_000)


class CatalogBridgeImage(CatalogBridgeModel):
    url: HttpUrl
    alt_text: str | None = Field(default=None, alias="altText", max_length=1_000)
    position: int | None = Field(default=None, ge=0, le=10_000)
    variant_id: str | None = Field(default=None, alias="variantId", max_length=500)


class CatalogBridgeVariant(CatalogBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    sku: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=1_000)
    price: str | None = Field(default=None, max_length=100)
    compare_at_price: str | None = Field(default=None, alias="compareAtPrice", max_length=100)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability: str | None = Field(default=None, max_length=100)
    options: dict[str, JsonValue] = Field(default_factory=dict, max_length=200)
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=500)
    images: list[CatalogBridgeImage] = Field(default_factory=list, max_length=100)
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @field_validator("options", "attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _validate_catalog_value(value)  # type: ignore[return-value]


class CatalogBridgeProduct(CatalogBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=100_000)
    slug: str | None = Field(default=None, max_length=1_000)
    url: HttpUrl | None = None
    canonical_url: HttpUrl | None = Field(default=None, alias="canonicalUrl")
    status: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=500)
    product_type: str | None = Field(default=None, alias="productType", max_length=500)
    categories: list[str] = Field(default_factory=list, max_length=100)
    collections: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=500)
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=500)
    seo: CatalogBridgeSeo = Field(default_factory=CatalogBridgeSeo)
    images: list[CatalogBridgeImage] = Field(default_factory=list, max_length=500)
    variants: list[CatalogBridgeVariant] = Field(default_factory=list, max_length=2_000)
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _validate_catalog_value(value)  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        variant_ids = [variant.id for variant in self.variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("Variant IDs must be unique inside a product")
        known_variants = set(variant_ids)
        if any(image.variant_id and image.variant_id not in known_variants for image in self.images):
            raise ValueError("Image variantId must reference a variant in the same product")
        return self


class CatalogBridgeSourceCreateRequest(CatalogBridgeModel):
    name: str = Field(min_length=2, max_length=200)


class CatalogBridgeSourceProvisionResponse(CatalogBridgeModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    endpoint: HttpUrl
    token: str = Field(min_length=32)
    token_fingerprint: str = Field(alias="tokenFingerprint", min_length=12, max_length=12)
    protocol_version: str = Field(alias="protocolVersion")


class CatalogBridgeSnapshotManifest(CatalogBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    started_at: datetime = Field(alias="startedAt")
    declared_product_count: int = Field(alias="declaredProductCount", ge=0)
    declared_variant_count: int = Field(alias="declaredVariantCount", ge=0)
    source_label: str | None = Field(default=None, alias="sourceLabel", max_length=200)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=30)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class CatalogBridgeBatch(CatalogBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    sequence: int = Field(ge=0)
    records: list[CatalogBridgeProduct] = Field(
        min_length=1,
        max_length=CATALOG_BRIDGE_MAX_BATCH_RECORDS,
    )

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class CatalogBridgeCompleteRequest(CatalogBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    batch_count: int = Field(alias="batchCount", gt=0)
    product_count: int = Field(alias="productCount", ge=0)
    variant_count: int = Field(alias="variantCount", ge=0)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class CatalogBridgeSnapshotStatus(CatalogBridgeModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    status: str
    accepted_batches: int = Field(alias="acceptedBatches", ge=0)
    accepted_products: int = Field(alias="acceptedProducts", ge=0)
    accepted_variants: int = Field(alias="acceptedVariants", ge=0)
    ingestion_job_id: uuid.UUID | None = Field(default=None, alias="ingestionJobId")
