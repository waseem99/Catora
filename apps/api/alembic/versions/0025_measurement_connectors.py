"""Add aggregate measurement providers, properties, observations, attribution and annotations.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "measurement_provider_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("external_account_id", sa.String(500), nullable=False),
        sa.Column("credential_reference", sa.String(500), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sync_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_measurement_account_workspace_provider_external",
        ),
    )
    op.create_index(
        "ix_measurement_accounts_workspace_status",
        "measurement_provider_accounts",
        ["workspace_id", "status"],
    )
    op.create_table(
        "measurement_properties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_property_id", sa.String(500), nullable=False),
        sa.Column("property_type", sa.String(60), nullable=False),
        sa.Column("display_name", sa.String(500), nullable=True),
        sa.Column("canonical_origin", sa.String(2000), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_account_id"],
            ["measurement_provider_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider_account_id",
            "external_property_id",
            name="uq_measurement_property_account_external",
        ),
    )
    op.create_index(
        "ix_measurement_properties_workspace_status",
        "measurement_properties",
        ["workspace_id", "status"],
    )
    op.create_table(
        "measurement_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("measurement_property_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("metric_key", sa.String(160), nullable=False),
        sa.Column("metric_version", sa.String(100), nullable=False),
        sa.Column("value_microunits", sa.BigInteger(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dimension_hash", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("sample_state", sa.String(30), nullable=False),
        sa.Column("freshness_state", sa.String(30), nullable=False),
        sa.Column("source_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["measurement_property_id"],
            ["measurement_properties.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "measurement_property_id",
            "metric_key",
            "dimension_hash",
            "window_start",
            "window_end",
            "observation_hash",
            name="uq_measurement_observation_metric_window_hash",
        ),
    )
    op.create_index(
        "ix_measurement_observations_workspace_metric_window",
        "measurement_observations",
        ["workspace_id", "metric_key", "window_start", "window_end"],
    )
    op.create_index(
        "ix_measurement_observations_property_freshness",
        "measurement_observations",
        ["measurement_property_id", "observed_at"],
    )
    op.create_table(
        "measurement_attribution_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("measurement_observation_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("attribution_state", sa.String(30), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("confidence_basis_points", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["measurement_observation_id"],
            ["measurement_observations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "measurement_observation_id",
            "target_type",
            "target_id",
            name="uq_measurement_attribution_observation_target",
        ),
    )
    op.create_index(
        "ix_measurement_attribution_workspace_state",
        "measurement_attribution_links",
        ["workspace_id", "attribution_state"],
    )
    op.create_table(
        "measurement_change_annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("annotation_type", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_revision", sa.String(100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_measurement_annotations_workspace_occurred",
        "measurement_change_annotations",
        ["workspace_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_annotations_workspace_occurred",
        table_name="measurement_change_annotations",
    )
    op.drop_table("measurement_change_annotations")
    op.drop_index(
        "ix_measurement_attribution_workspace_state",
        table_name="measurement_attribution_links",
    )
    op.drop_table("measurement_attribution_links")
    op.drop_index(
        "ix_measurement_observations_property_freshness",
        table_name="measurement_observations",
    )
    op.drop_index(
        "ix_measurement_observations_workspace_metric_window",
        table_name="measurement_observations",
    )
    op.drop_table("measurement_observations")
    op.drop_index(
        "ix_measurement_properties_workspace_status",
        table_name="measurement_properties",
    )
    op.drop_table("measurement_properties")
    op.drop_index(
        "ix_measurement_accounts_workspace_status",
        table_name="measurement_provider_accounts",
    )
    op.drop_table("measurement_provider_accounts")
