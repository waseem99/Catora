"""add persisted recommendation jobs

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_jobs",
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("audit_finding_id", sa.Uuid(), nullable=True),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("budget_microunits", sa.BigInteger(), nullable=False),
        sa.Column(
            "request_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "failure_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name=op.f("ck_recommendation_jobs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_finding_id"],
            ["audit_findings.id"],
            name=op.f("fk_recommendation_jobs_audit_finding_id_audit_findings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_recommendation_jobs_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name=op.f("fk_recommendation_jobs_recommendation_id_recommendations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_recommendation_jobs_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_recommendation_jobs_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_recommendation_jobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_jobs")),
    )
    op.create_index(
        op.f("ix_recommendation_jobs_audit_finding_id"),
        "recommendation_jobs",
        ["audit_finding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_jobs_product_id"),
        "recommendation_jobs",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_jobs_recommendation_id"),
        "recommendation_jobs",
        ["recommendation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_jobs_requested_by_user_id"),
        "recommendation_jobs",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_jobs_variant_id"),
        "recommendation_jobs",
        ["variant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_jobs_workspace_id"),
        "recommendation_jobs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_jobs_workspace_status_created",
        "recommendation_jobs",
        ["workspace_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_jobs_workspace_status_created",
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_workspace_id"),
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_variant_id"),
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_requested_by_user_id"),
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_recommendation_id"),
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_product_id"),
        table_name="recommendation_jobs",
    )
    op.drop_index(
        op.f("ix_recommendation_jobs_audit_finding_id"),
        table_name="recommendation_jobs",
    )
    op.drop_table("recommendation_jobs")
