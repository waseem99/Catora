"""add restaurant domain, evidence, and freshness contracts

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "restaurant_brands",
        *_identity_columns(),
        sa.Column("catalog_source_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("legal_name", sa.String(length=500), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("projection_version", sa.String(length=100), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_brand_status",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_source_id"],
            ["catalog_sources.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("workspace_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_brands_workspace_id",
        "restaurant_brands",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_brands_catalog_source_id",
        "restaurant_brands",
        ["catalog_source_id"],
    )

    op.create_table(
        "restaurant_locations",
        *_identity_columns(),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_source_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("external_location_id", sa.String(length=500), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("ordering_url", sa.Text(), nullable=True),
        sa.Column(
            "address",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column(
            "regular_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "special_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "service_modes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "facilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "cuisine_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("projection_version", sa.String(length=100), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','temporarily_closed','inactive','retired')",
            name="valid_restaurant_location_status",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["restaurant_brands.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_source_id"],
            ["catalog_sources.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("workspace_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_locations_workspace_id",
        "restaurant_locations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_locations_brand_id",
        "restaurant_locations",
        ["brand_id"],
    )
    op.create_index(
        "ix_restaurant_locations_catalog_source_id",
        "restaurant_locations",
        ["catalog_source_id"],
    )
    op.create_index(
        "ix_restaurant_locations_external_location_id",
        "restaurant_locations",
        ["external_location_id"],
    )

    op.create_table(
        "restaurant_identity_aliases",
        *_identity_columns(),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_alias", sa.String(length=500), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item')",
            name="valid_restaurant_alias_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','retired')",
            name="valid_restaurant_alias_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_id",
            "normalized_alias",
        ),
    )
    op.create_index(
        "ix_restaurant_identity_aliases_workspace_id",
        "restaurant_identity_aliases",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_identity_aliases_source_record_id",
        "restaurant_identity_aliases",
        ["source_record_id"],
    )
    op.create_index(
        "ix_restaurant_identity_alias_lookup",
        "restaurant_identity_aliases",
        ["workspace_id", "entity_type", "normalized_alias"],
    )

    op.create_table(
        "restaurant_service_areas",
        *_identity_columns(),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("area_type", sa.String(length=40), nullable=False),
        sa.Column(
            "geometry",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("ordering_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "area_type IN "
            "('city','district','neighborhood','postal_code','polygon','radius')",
            name="valid_restaurant_service_area_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_service_area_status",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["restaurant_locations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("location_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_service_areas_workspace_id",
        "restaurant_service_areas",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_service_areas_location_id",
        "restaurant_service_areas",
        ["location_id"],
    )

    op.create_table(
        "restaurant_menus",
        *_identity_columns(),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("catalog_source_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_menu_status",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["restaurant_brands.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["restaurant_locations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_source_id"],
            ["catalog_sources.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("workspace_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_menus_workspace_id",
        "restaurant_menus",
        ["workspace_id"],
    )
    op.create_index("ix_restaurant_menus_brand_id", "restaurant_menus", ["brand_id"])
    op.create_index(
        "ix_restaurant_menus_location_id",
        "restaurant_menus",
        ["location_id"],
    )
    op.create_index(
        "ix_restaurant_menus_catalog_source_id",
        "restaurant_menus",
        ["catalog_source_id"],
    )

    op.create_table(
        "restaurant_menu_sections",
        *_identity_columns(),
        sa.Column("menu_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["menu_id"],
            ["restaurant_menus.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("menu_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_menu_sections_workspace_id",
        "restaurant_menu_sections",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_menu_sections_menu_id",
        "restaurant_menu_sections",
        ["menu_id"],
    )

    op.create_table(
        "restaurant_menu_items",
        *_identity_columns(),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "dietary_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "allergen_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("availability_state", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "availability_state IN "
            "('available','unavailable','unknown','not_applicable','conflicting','stale')",
            name="valid_restaurant_menu_item_availability",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive','retired')",
            name="valid_restaurant_menu_item_status",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["restaurant_menu_sections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("section_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_menu_items_workspace_id",
        "restaurant_menu_items",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_menu_items_section_id",
        "restaurant_menu_items",
        ["section_id"],
    )
    op.create_index(
        "ix_restaurant_menu_items_product_id",
        "restaurant_menu_items",
        ["product_id"],
    )

    op.create_table(
        "restaurant_modifier_groups",
        *_identity_columns(),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("min_selections", sa.Integer(), nullable=False),
        sa.Column("max_selections", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "min_selections >= 0 AND max_selections >= min_selections",
            name="valid_restaurant_modifier_selection_range",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"],
            ["restaurant_menu_items.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("menu_item_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_modifier_groups_workspace_id",
        "restaurant_modifier_groups",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_modifier_groups_menu_item_id",
        "restaurant_modifier_groups",
        ["menu_item_id"],
    )

    op.create_table(
        "restaurant_modifier_options",
        *_identity_columns(),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("price_delta", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("availability_state", sa.String(length=30), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "availability_state IN ('available','unavailable','unknown','stale')",
            name="valid_restaurant_modifier_option_availability",
        ),
        sa.ForeignKeyConstraint(
            ["modifier_group_id"],
            ["restaurant_modifier_groups.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("modifier_group_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_modifier_options_workspace_id",
        "restaurant_modifier_options",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_modifier_options_modifier_group_id",
        "restaurant_modifier_options",
        ["modifier_group_id"],
    )

    op.create_table(
        "restaurant_offers_promotions",
        *_identity_columns(),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("menu_item_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "status IN ('scheduled','active','expired','cancelled','unknown')",
            name="valid_restaurant_offer_status",
        ),
        sa.CheckConstraint(
            "brand_id IS NOT NULL OR location_id IS NOT NULL OR menu_item_id IS NOT NULL",
            name="restaurant_offer_has_scope",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["restaurant_brands.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["restaurant_locations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"],
            ["restaurant_menu_items.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "canonical_key"),
    )
    op.create_index(
        "ix_restaurant_offers_promotions_workspace_id",
        "restaurant_offers_promotions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_offers_promotions_brand_id",
        "restaurant_offers_promotions",
        ["brand_id"],
    )
    op.create_index(
        "ix_restaurant_offers_promotions_location_id",
        "restaurant_offers_promotions",
        ["location_id"],
    )
    op.create_index(
        "ix_restaurant_offers_promotions_menu_item_id",
        "restaurant_offers_promotions",
        ["menu_item_id"],
    )

    op.create_table(
        "restaurant_freshness_policies",
        *_identity_columns(),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("fact_key", sa.String(length=160), nullable=False),
        sa.Column("warning_age_seconds", sa.Integer(), nullable=False),
        sa.Column("max_age_seconds", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item','offer')",
            name="valid_restaurant_freshness_entity_type",
        ),
        sa.CheckConstraint(
            "warning_age_seconds >= 0 AND max_age_seconds > warning_age_seconds",
            name="valid_restaurant_freshness_ages",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "entity_type",
            "fact_key",
            "policy_version",
        ),
    )
    op.create_index(
        "ix_restaurant_freshness_policies_workspace_id",
        "restaurant_freshness_policies",
        ["workspace_id"],
    )

    op.create_table(
        "restaurant_fact_observations",
        *_identity_columns(),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("fact_key", sa.String(length=160), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("value_type", sa.String(length=50), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("locale", sa.String(length=35), nullable=True),
        sa.Column("fact_state", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(length=100), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('brand','location','service_area','menu','menu_item','offer')",
            name="valid_restaurant_fact_entity_type",
        ),
        sa.CheckConstraint(
            "fact_state IN "
            "('supported','partial','unsupported','stale','conflicting','inaccessible')",
            name="valid_restaurant_fact_state",
        ),
        sa.CheckConstraint(
            "confidence IN ('high','medium','low')",
            name="valid_restaurant_fact_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            "entity_type",
            "entity_id",
            "fact_key",
            "checksum",
        ),
    )
    op.create_index(
        "ix_restaurant_fact_observations_workspace_id",
        "restaurant_fact_observations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_restaurant_fact_observations_source_record_id",
        "restaurant_fact_observations",
        ["source_record_id"],
    )
    op.create_index(
        "ix_restaurant_fact_current_lookup",
        "restaurant_fact_observations",
        ["workspace_id", "entity_type", "entity_id", "fact_key", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("restaurant_fact_observations")
    op.drop_table("restaurant_freshness_policies")
    op.drop_table("restaurant_offers_promotions")
    op.drop_table("restaurant_modifier_options")
    op.drop_table("restaurant_modifier_groups")
    op.drop_table("restaurant_menu_items")
    op.drop_table("restaurant_menu_sections")
    op.drop_table("restaurant_menus")
    op.drop_table("restaurant_service_areas")
    op.drop_table("restaurant_identity_aliases")
    op.drop_table("restaurant_locations")
    op.drop_table("restaurant_brands")
