"""Add provider-neutral off-page authority observations and governed outreach.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authority_provider_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_account_id", sa.String(500), nullable=False),
        sa.Column("credential_reference", sa.String(500), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sync_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_authority_account_workspace_provider_external",
        ),
    )
    op.create_index(
        "ix_authority_accounts_workspace_status",
        "authority_provider_accounts",
        ["workspace_id", "status"],
    )
    op.create_table(
        "authority_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_observation_id", sa.String(500), nullable=False),
        sa.Column("observation_type", sa.String(50), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(500), nullable=True),
        sa.Column("anchor_or_mention_text", sa.Text(), nullable=True),
        sa.Column("provider_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("identity_state", sa.String(30), nullable=False),
        sa.Column("identity_method", sa.String(100), nullable=False),
        sa.Column("link_state", sa.String(30), nullable=False),
        sa.Column("nofollow", sa.Boolean(), nullable=True),
        sa.Column("sponsored", sa.Boolean(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_account_id"], ["authority_provider_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_account_id",
            "external_observation_id",
            "observation_hash",
            name="uq_authority_observation_account_external_hash",
        ),
    )
    op.create_index(
        "ix_authority_observations_workspace_type_observed",
        "authority_observations",
        ["workspace_id", "observation_type", "observed_at"],
    )
    op.create_table(
        "authority_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("authority_observation_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_type", sa.String(60), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("risk_state", sa.String(30), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("verification_method", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.String(100), nullable=False),
        sa.Column("evidence_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score_basis_points", sa.Integer(), nullable=False),
        sa.Column("score_version", sa.String(100), nullable=False),
        sa.Column("opportunity_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["authority_observation_id"], ["authority_observations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "opportunity_fingerprint",
            name="uq_authority_opportunity_workspace_fingerprint",
        ),
    )
    op.create_index(
        "ix_authority_opportunities_workspace_state_score",
        "authority_opportunities",
        ["workspace_id", "state", "score_basis_points"],
    )
    op.create_table(
        "authority_suppressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_target", sa.String(500), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "normalized_target",
            name="uq_authority_suppression_workspace_target",
        ),
    )
    op.create_table(
        "authority_outreach_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("factual_claims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("suppression_checked", sa.Boolean(), nullable=False),
        sa.Column("legal_basis_confirmed", sa.Boolean(), nullable=False),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["authority_opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["generated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "opportunity_id",
            "draft_version",
            name="uq_authority_outreach_workspace_opportunity_version",
        ),
    )
    op.create_index(
        "ix_authority_outreach_workspace_status",
        "authority_outreach_drafts",
        ["workspace_id", "status"],
    )
    op.create_table(
        "authority_outreach_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["authority_outreach_drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            name="uq_authority_outreach_decision_workspace_draft",
        ),
    )


def downgrade() -> None:
    op.drop_table("authority_outreach_decisions")
    op.drop_index("ix_authority_outreach_workspace_status", table_name="authority_outreach_drafts")
    op.drop_table("authority_outreach_drafts")
    op.drop_table("authority_suppressions")
    op.drop_index(
        "ix_authority_opportunities_workspace_state_score",
        table_name="authority_opportunities",
    )
    op.drop_table("authority_opportunities")
    op.drop_index(
        "ix_authority_observations_workspace_type_observed",
        table_name="authority_observations",
    )
    op.drop_table("authority_observations")
    op.drop_index(
        "ix_authority_accounts_workspace_status",
        table_name="authority_provider_accounts",
    )
    op.drop_table("authority_provider_accounts")
