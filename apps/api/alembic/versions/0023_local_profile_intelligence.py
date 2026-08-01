"""Add local profile provider observations, branch links, and conflicts.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_profile_provider_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_account_id", sa.String(length=500), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=True),
        sa.Column("credential_reference", sa.String(length=500), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
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
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_local_profile_account_workspace_provider_external",
        ),
    )
    op.create_index(
        "ix_local_profile_accounts_workspace_status",
        "local_profile_provider_accounts",
        ["workspace_id", "status"],
        unique=False,
    )

    op.create_table(
        "local_profile_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_profile_id", sa.String(length=500), nullable=False),
        sa.Column("provider_location_name", sa.String(length=1000), nullable=True),
        sa.Column("profile_state", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("website_url", sa.String(length=2000), nullable=True),
        sa.Column("menu_url", sa.String(length=2000), nullable=True),
        sa.Column("ordering_url", sa.String(length=2000), nullable=True),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latitude", sa.String(length=50), nullable=True),
        sa.Column("longitude", sa.String(length=50), nullable=True),
        sa.Column("regular_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("special_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("service_areas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("media_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completeness", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_fields_present", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["local_profile_provider_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_account_id",
            "external_profile_id",
            "observation_hash",
            name="uq_local_profile_observation_account_profile_hash",
        ),
    )
    op.create_index(
        "ix_local_profile_observations_workspace_profile_observed",
        "local_profile_observations",
        ["workspace_id", "external_profile_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_local_profile_observations_account_current",
        "local_profile_observations",
        ["provider_account_id", "is_current"],
        unique=False,
    )

    op.create_table(
        "branch_local_profile_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_location_id", sa.Uuid(), nullable=True),
        sa.Column("provider_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_profile_id", sa.String(length=500), nullable=False),
        sa.Column("match_state", sa.String(length=30), nullable=False),
        sa.Column("match_method", sa.String(length=100), nullable=False),
        sa.Column("confidence_basis_points", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_location_id"],
            ["restaurant_locations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["local_profile_provider_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "restaurant_location_id",
            "provider_account_id",
            name="uq_branch_local_profile_link_location_account",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "provider_account_id",
            "external_profile_id",
            name="uq_branch_local_profile_link_account_profile",
        ),
    )
    op.create_index(
        "ix_branch_local_profile_links_workspace_state",
        "branch_local_profile_links",
        ["workspace_id", "match_state"],
        unique=False,
    )

    op.create_table(
        "local_profile_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("branch_profile_link_id", sa.Uuid(), nullable=False),
        sa.Column("local_profile_observation_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("restaurant_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_profile_link_id"],
            ["branch_local_profile_links.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["local_profile_observation_id"],
            ["local_profile_observations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "branch_profile_link_id",
            "field_key",
            "fingerprint",
            name="uq_local_profile_conflict_link_field_fingerprint",
        ),
    )
    op.create_index(
        "ix_local_profile_conflicts_workspace_status_severity",
        "local_profile_conflicts",
        ["workspace_id", "status", "severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_local_profile_conflicts_workspace_status_severity",
        table_name="local_profile_conflicts",
    )
    op.drop_table("local_profile_conflicts")
    op.drop_index(
        "ix_branch_local_profile_links_workspace_state",
        table_name="branch_local_profile_links",
    )
    op.drop_table("branch_local_profile_links")
    op.drop_index(
        "ix_local_profile_observations_account_current",
        table_name="local_profile_observations",
    )
    op.drop_index(
        "ix_local_profile_observations_workspace_profile_observed",
        table_name="local_profile_observations",
    )
    op.drop_table("local_profile_observations")
    op.drop_index(
        "ix_local_profile_accounts_workspace_status",
        table_name="local_profile_provider_accounts",
    )
    op.drop_table("local_profile_provider_accounts")
