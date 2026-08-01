"""Add governed Git repository connections and change proposals.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "git_repository_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("repository_full_name", sa.String(length=500), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("allowed_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "protected_branches",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("credential_reference", sa.String(length=500), nullable=False),
        sa.Column(
            "capability_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
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
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "repository_full_name",
            name="uq_git_repository_connection_workspace_provider_repo",
        ),
    )
    op.create_index(
        "ix_git_repository_connections_workspace_status",
        "git_repository_connections",
        ["workspace_id", "status"],
        unique=False,
    )

    op.create_table(
        "git_change_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_connection_id", sa.Uuid(), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("base_revision", sa.String(length=64), nullable=False),
        sa.Column("proposal_branch", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "patch_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("patch_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("rollback_plan", sa.Text(), nullable=False),
        sa.Column(
            "conflict_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("provider_pr_number", sa.Integer(), nullable=True),
        sa.Column("provider_pr_url", sa.String(length=2_000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_revision", sa.String(length=64), nullable=True),
        sa.Column(
            "validation_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["repository_connection_id"],
            ["git_repository_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["change_set_id"],
            ["change_sets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_connection_id",
            "idempotency_key",
            name="uq_git_change_proposal_connection_idempotency",
        ),
    )
    op.create_index(
        "ix_git_change_proposals_workspace_status_created",
        "git_change_proposals",
        ["workspace_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_git_change_proposals_workspace_status_created",
        table_name="git_change_proposals",
    )
    op.drop_table("git_change_proposals")
    op.drop_index(
        "ix_git_repository_connections_workspace_status",
        table_name="git_repository_connections",
    )
    op.drop_table("git_repository_connections")
