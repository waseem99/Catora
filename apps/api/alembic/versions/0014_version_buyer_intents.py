"""version buyer intents

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "buyer_intents",
        sa.Column("lineage_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "buyer_intents",
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
    )
    op.execute(sa.text("UPDATE buyer_intents SET lineage_id = id WHERE lineage_id IS NULL"))
    op.alter_column("buyer_intents", "lineage_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_buyer_intents_supersedes_id_buyer_intents"),
        "buyer_intents",
        "buyer_intents",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_buyer_intents_valid_approval_status"),
        "buyer_intents",
        "approval_status IN ('draft','approved','superseded')",
    )
    op.create_unique_constraint(
        op.f("uq_buyer_intents_workspace_id"),
        "buyer_intents",
        ["workspace_id", "lineage_id", "version"],
    )
    op.create_index(
        "ix_buyer_intents_lineage_id",
        "buyer_intents",
        ["lineage_id"],
        unique=False,
    )
    op.create_index(
        "ix_buyer_intents_supersedes_id",
        "buyer_intents",
        ["supersedes_id"],
        unique=False,
    )
    op.create_index(
        "ix_buyer_intents_workspace_lineage_version",
        "buyer_intents",
        ["workspace_id", "lineage_id", "version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_buyer_intents_workspace_lineage_version",
        table_name="buyer_intents",
    )
    op.drop_index("ix_buyer_intents_supersedes_id", table_name="buyer_intents")
    op.drop_index("ix_buyer_intents_lineage_id", table_name="buyer_intents")
    op.drop_constraint(
        op.f("uq_buyer_intents_workspace_id"),
        "buyer_intents",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_buyer_intents_valid_approval_status"),
        "buyer_intents",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_buyer_intents_supersedes_id_buyer_intents"),
        "buyer_intents",
        type_="foreignkey",
    )
    op.drop_column("buyer_intents", "supersedes_id")
    op.drop_column("buyer_intents", "lineage_id")
