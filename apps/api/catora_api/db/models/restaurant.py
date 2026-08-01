from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict
LIST_DEFAULT = list


class RestaurantBrand(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_brands"
    __table_args__ = (
        UniqueConstraint("workspace_id", "canonical_key"),
        CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_brand_status",
        ),
    )

    catalog_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("catalog_sources.id", ondelete="SET NULL"),
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    projection_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="restaurant-domain/v1",
    )
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RestaurantLocation(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_locations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "canonical_key"),
        CheckConstraint(
            "status IN ('active','temporarily_closed','inactive','retired')",
            name="valid_restaurant_location_status",
        ),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("catalog_sources.id", ondelete="SET NULL"),
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    external_location_id: Mapped[str | None] = mapped_column(String(500), index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(100))
    website_url: Mapped[str | None] = mapped_column(Text)
    ordering_url: Mapped[str | None] = mapped_column(Text)
    address: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=JSON_DEFAULT,
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    regular_hours: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=JSON_DEFAULT,
    )
    special_hours: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=LIST_DEFAULT,
    )
    service_modes: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=LIST_DEFAULT,
    )
    facilities: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=LIST_DEFAULT,
    )
    cuisine_types: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=LIST_DEFAULT,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    projection_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="restaurant-domain/v1",
    )
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RestaurantIdentityAlias(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_identity_aliases"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_id",
            "normalized_alias",
        ),
        CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item')",
            name="valid_restaurant_alias_entity_type",
        ),
        CheckConstraint(
            "status IN ('active','retired')",
            name="valid_restaurant_alias_status",
        ),
        Index(
            "ix_restaurant_identity_alias_lookup",
            "workspace_id",
            "entity_type",
            "normalized_alias",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(500), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("source_records.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class RestaurantServiceArea(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_service_areas"
    __table_args__ = (
        UniqueConstraint("location_id", "canonical_key"),
        CheckConstraint(
            "area_type IN ('city','district','neighborhood','postal_code','polygon','radius')",
            name="valid_restaurant_service_area_type",
        ),
        CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_service_area_status",
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    area_type: Mapped[str] = mapped_column(String(40), nullable=False)
    geometry: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=JSON_DEFAULT,
    )
    ordering_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class RestaurantMenu(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "restaurant_menus"
    __table_args__ = (
        UniqueConstraint("workspace_id", "canonical_key"),
        CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_menu_status",
        ),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("catalog_sources.id", ondelete="SET NULL"),
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RestaurantMenuSection(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_menu_sections"
    __table_args__ = (UniqueConstraint("menu_id", "canonical_key"),)

    menu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_menus.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RestaurantMenuItem(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_menu_items"
    __table_args__ = (
        UniqueConstraint("section_id", "canonical_key"),
        CheckConstraint(
            "availability_state IN "
            "('available','unavailable','unknown','not_applicable','conflicting','stale')",
            name="valid_restaurant_menu_item_availability",
        ),
        CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_menu_item_status",
        ),
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_menu_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    dietary_facts: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=JSON_DEFAULT,
    )
    allergen_facts: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=JSON_DEFAULT,
    )
    availability_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unknown",
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RestaurantModifierGroup(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_modifier_groups"
    __table_args__ = (
        UniqueConstraint("menu_item_id", "canonical_key"),
        CheckConstraint(
            "min_selections >= 0 AND max_selections >= min_selections",
            name="valid_restaurant_modifier_selection_range",
        ),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_menu_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RestaurantModifierOption(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_modifier_options"
    __table_args__ = (
        UniqueConstraint("modifier_group_id", "canonical_key"),
        CheckConstraint(
            "availability_state IN ('available','unavailable','unknown','stale')",
            name="valid_restaurant_modifier_option_availability",
        ),
    )

    modifier_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurant_modifier_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    price_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    availability_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unknown",
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RestaurantOfferOrPromotion(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_offers_promotions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "canonical_key"),
        CheckConstraint(
            "status IN ('scheduled','active','expired','cancelled','unknown')",
            name="valid_restaurant_offer_status",
        ),
        CheckConstraint(
            "brand_id IS NOT NULL OR location_id IS NOT NULL OR menu_item_id IS NOT NULL",
            name="restaurant_offer_has_scope",
        ),
    )

    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("restaurant_brands.id", ondelete="CASCADE"),
        index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        index=True,
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("restaurant_menu_items.id", ondelete="CASCADE"),
        index=True,
    )
    canonical_key: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RestaurantFreshnessPolicy(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_freshness_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_type", "fact_key", "policy_version"),
        CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item','offer')",
            name="valid_restaurant_freshness_entity_type",
        ),
        CheckConstraint(
            "warning_age_seconds >= 0 AND max_age_seconds > warning_age_seconds",
            name="valid_restaurant_freshness_ages",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(160), nullable=False)
    warning_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class RestaurantFactObservation(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "restaurant_fact_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "entity_type",
            "entity_id",
            "fact_key",
            "checksum",
        ),
        CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item','offer')",
            name="valid_restaurant_fact_entity_type",
        ),
        CheckConstraint(
            "fact_state IN "
            "('supported','partial','unsupported','stale','conflicting','inaccessible')",
            name="valid_restaurant_fact_state",
        ),
        CheckConstraint(
            "confidence IN ('high','medium','low')",
            name="valid_restaurant_fact_confidence",
        ),
        Index(
            "ix_restaurant_fact_current_lookup",
            "workspace_id",
            "entity_type",
            "entity_id",
            "fact_key",
            "observed_at",
        ),
    )

    source_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("source_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    fact_key: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[dict[str, object] | list[object] | str | int | float | bool | None] = (
        mapped_column(JSONB)
    )
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    locale: Mapped[str | None] = mapped_column(String(35))
    fact_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="supported",
    )
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str | None] = mapped_column(String(100))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
