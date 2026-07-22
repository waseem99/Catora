"""add intent suites

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "intent_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intent_suites_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_suites")),
    )
    op.create_index(
        op.f("ix_intent_suites_workspace_id"),
        "intent_suites",
        ["workspace_id"],
        unique=False,
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "intent_suite_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("intent_suite_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_intent_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_intent_suite_members_valid_position"),
        ),
        sa.ForeignKeyConstraint(
            ["buyer_intent_id"],
            ["buyer_intents.id"],
            name=op.f("fk_intent_suite_members_buyer_intent_id_buyer_intents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intent_suite_id"],
            ["intent_suites.id"],
            name=op.f("fk_intent_suite_members_intent_suite_id_intent_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intent_suite_members_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_suite_members")),
        sa.UniqueConstraint(
            "intent_suite_id",
            "buyer_intent_id",
            name=op.f("uq_intent_suite_members_intent_suite_id"),
        ),
        sa.UniqueConstraint(
            "intent_suite_id",
            "position",
            name="uq_intent_suite_members_suite_position",
        ),
    )
    op.create_index(
        op.f("ix_intent_suite_members_workspace_id"),
        "intent_suite_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intent_suite_members_intent_suite_id"),
        "intent_suite_members",
        ["intent_suite_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intent_suite_members_buyer_intent_id"),
        "intent_suite_members",
        ["buyer_intent_id"],
        unique=False,
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "intent_suite_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("intent_suite_id", sa.Uuid(), nullable=False),
        sa.Column("previous_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "requested_product_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ('running','completed','failed')",
            name=op.f("ck_intent_suite_runs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["intent_suite_id"],
            ["intent_suites.id"],
            name=op.f("fk_intent_suite_runs_intent_suite_id_intent_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_run_id"],
            ["intent_suite_runs.id"],
            name=op.f("fk_intent_suite_runs_previous_run_id_intent_suite_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intent_suite_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_suite_runs")),
    )
    op.create_index(
        op.f("ix_intent_suite_runs_workspace_id"),
        "intent_suite_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intent_suite_runs_intent_suite_id"),
        "intent_suite_runs",
        ["intent_suite_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intent_suite_runs_previous_run_id"),
        "intent_suite_runs",
        ["previous_run_id"],
        unique=False,
    )

    op.add_column(
        "intent_runs",
        sa.Column("intent_suite_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_intent_runs_intent_suite_run_id_intent_suite_runs"),
        "intent_runs",
        "intent_suite_runs",
        ["intent_suite_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_intent_runs_intent_suite_run_id"),
        "intent_runs",
        ["intent_suite_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_intent_runs_intent_suite_run_id"),
        table_name="intent_runs",
    )
    op.drop_constraint(
        op.f("fk_intent_runs_intent_suite_run_id_intent_suite_runs"),
        "intent_runs",
        type_="foreignkey",
    )
    op.drop_column("intent_runs", "intent_suite_run_id")

    op.drop_index(
        op.f("ix_intent_suite_runs_previous_run_id"),
        table_name="intent_suite_runs",
    )
    op.drop_index(
        op.f("ix_intent_suite_runs_intent_suite_id"),
        table_name="intent_suite_runs",
    )
    op.drop_index(
        op.f("ix_intent_suite_runs_workspace_id"),
        table_name="intent_suite_runs",
    )
    op.drop_table("intent_suite_runs")

    op.drop_index(
        op.f("ix_intent_suite_members_buyer_intent_id"),
        table_name="intent_suite_members",
    )
    op.drop_index(
        op.f("ix_intent_suite_members_intent_suite_id"),
        table_name="intent_suite_members",
    )
    op.drop_index(
        op.f("ix_intent_suite_members_workspace_id"),
        table_name="intent_suite_members",
    )
    op.drop_table("intent_suite_members")

    op.drop_index(
        op.f("ix_intent_suites_workspace_id"),
        table_name="intent_suites",
    )
    op.drop_table("intent_suites")
