"""add workspace enrichment policies

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_enrichment_policies",
        sa.Column(
            "brand_controls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("max_run_budget_microunits", sa.BigInteger(), nullable=True),
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
            name=op.f(
                "fk_workspace_enrichment_policies_workspace_id_workspaces"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_workspace_enrichment_policies"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            name=op.f("uq_workspace_enrichment_policies_workspace_id"),
        ),
    )
    op.create_index(
        op.f("ix_workspace_enrichment_policies_workspace_id"),
        "workspace_enrichment_policies",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workspace_enrichment_policies_workspace_id"),
        table_name="workspace_enrichment_policies",
    )
    op.drop_table("workspace_enrichment_policies")
