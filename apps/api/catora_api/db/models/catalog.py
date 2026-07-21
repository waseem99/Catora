from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict


class CatalogSource(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "catalog_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('shopify','csv','sitemap','urls')", name="valid_source_type"
        ),
    )
    storefront_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("storefronts.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=JSON_DEFAULT)
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','validating','running','partially_completed',"
            "'completed','failed','cancelled')",
            name="valid_status",
        ),
    )
    catalog_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    checkpoint: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRecord(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("catalog_source_id", "external_id", "content_hash"),
        Index("ix_source_records_source_external", "catalog_source_id", "external_id"),
    )
    catalog_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingestion_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    record_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Category(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("workspace_id", "taxonomy_version", "key"),)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    key: Mapped[str] = mapped_column(String(150), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TaxonomyField(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_fields"
    __table_args__ = (UniqueConstraint("category_id", "key", "version"),)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(150), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    specification: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Product(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("workspace_id", "canonical_key"),)
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    primary_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductVariant(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "canonical_key"),)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    option_values: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductImage(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "product_images"
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    alt_text: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64))


class ProductAttribute(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "product_attributes"
    __table_args__ = (
        CheckConstraint(
            "value_state IN ('present','missing','unknown','not_applicable','conflicting')",
            name="valid_value_state",
        ),
        Index("ix_product_attributes_lookup", "product_id", "variant_id", "key"),
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(150), nullable=False)
    value: Mapped[dict[str, object] | list[object] | str | int | float | bool | None] = (
        mapped_column(JSONB)
    )
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    locale: Mapped[str | None] = mapped_column(String(35))
    value_state: Mapped[str] = mapped_column(String(30), nullable=False, default="present")
    transformer_version: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="high")


class EvidenceReference(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "evidence_references"
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="SET NULL"), index=True
    )
    attribute_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_attributes.id", ondelete="SET NULL"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(500), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
