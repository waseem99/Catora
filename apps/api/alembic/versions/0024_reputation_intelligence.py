"""Add review observations, analyses, and governed response drafts.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_provider_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_account_id", sa.String(500), nullable=False),
        sa.Column("credential_reference", sa.String(500), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sync_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_review_provider_account_workspace_provider_external",
        ),
    )
    op.create_index(
        "ix_review_accounts_workspace_status",
        "review_provider_accounts",
        ["workspace_id", "status"],
    )
    op.create_table(
        "review_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_location_id", sa.Uuid(), nullable=True),
        sa.Column("external_location_id", sa.String(500), nullable=True),
        sa.Column("external_review_id", sa.String(500), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(35), nullable=True),
        sa.Column("reviewer_display_name", sa.String(300), nullable=True),
        sa.Column("provider_response_text", sa.Text(), nullable=True),
        sa.Column("provider_response_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_state", sa.String(30), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_account_id"], ["review_provider_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_location_id"], ["restaurant_locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_account_id",
            "external_review_id",
            "observation_hash",
            name="uq_review_observation_account_review_hash",
        ),
    )
    op.create_index(
        "ix_review_observations_workspace_location_created",
        "review_observations",
        ["workspace_id", "restaurant_location_id", "review_created_at"],
    )
    op.create_index(
        "ix_review_observations_account_current",
        "review_observations",
        ["provider_account_id", "is_current"],
    )
    op.create_table(
        "review_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("review_observation_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_version", sa.String(100), nullable=False),
        sa.Column("themes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("praise", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("concerns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_level", sa.String(30), nullable=False),
        sa.Column("escalation_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_observation_id"], ["review_observations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "review_observation_id",
            "analysis_version",
            name="uq_review_analysis_observation_version",
        ),
    )
    op.create_index(
        "ix_review_analyses_workspace_risk",
        "review_analyses",
        ["workspace_id", "risk_level", "created_at"],
    )
    op.create_table(
        "review_response_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("review_observation_id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_observation_id"], ["review_observations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "review_observation_id",
            "draft_version",
            name="uq_review_response_draft_observation_version",
        ),
    )
    op.create_index(
        "ix_review_response_drafts_workspace_status",
        "review_response_drafts",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_response_drafts_workspace_status", table_name="review_response_drafts")
    op.drop_table("review_response_drafts")
    op.drop_index("ix_review_analyses_workspace_risk", table_name="review_analyses")
    op.drop_table("review_analyses")
    op.drop_index("ix_review_observations_account_current", table_name="review_observations")
    op.drop_index("ix_review_observations_workspace_location_created", table_name="review_observations")
    op.drop_table("review_observations")
    op.drop_index("ix_review_accounts_workspace_status", table_name="review_provider_accounts")
    op.drop_table("review_provider_accounts")
