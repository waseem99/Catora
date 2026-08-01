"""Add restaurant answer evaluation and external citation observations.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "restaurant_answer_suite_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("suite_key", sa.String(length=100), nullable=False),
        sa.Column("suite_version", sa.String(length=100), nullable=False),
        sa.Column("suite_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "definition",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "suite_key",
            "suite_version",
            name="uq_restaurant_answer_suite_workspace_key_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "suite_sha256",
            name="uq_restaurant_answer_suite_workspace_sha256",
        ),
    )
    op.create_index(
        "ix_restaurant_answer_suite_versions_workspace_id",
        "restaurant_answer_suite_versions",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "restaurant_answer_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("suite_version_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "input_snapshot",
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
            ["suite_version_id"],
            ["restaurant_answer_suite_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    op.create_index(
        "ix_restaurant_answer_runs_suite_version_id",
        "restaurant_answer_runs",
        ["suite_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_restaurant_answer_runs_workspace_id",
        "restaurant_answer_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_restaurant_answer_runs_workspace_entity_created",
        "restaurant_answer_runs",
        ["workspace_id", "entity_type", "entity_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "restaurant_answer_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_key", sa.String(length=100), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "fact_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
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
            ["run_id"],
            ["restaurant_answer_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "question_key"),
    )
    op.create_index(
        "ix_restaurant_answer_results_run_id",
        "restaurant_answer_results",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_restaurant_answer_results_workspace_id",
        "restaurant_answer_results",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_restaurant_answer_results_workspace_state",
        "restaurant_answer_results",
        ["workspace_id", "state"],
        unique=False,
    )

    op.create_table(
        "restaurant_external_citation_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_or_surface", sa.String(length=200), nullable=False),
        sa.Column("locale", sa.String(length=50), nullable=False),
        sa.Column("exact_query", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "cited_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("accuracy_state", sa.String(length=40), nullable=False),
        sa.Column(
            "verified_fact_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("provider_cost_microunits", sa.Integer(), nullable=True),
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
            "response_sha256",
            "observed_at",
        ),
    )
    op.create_index(
        "ix_restaurant_external_citation_observations_workspace_id",
        "restaurant_external_citation_observations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_restaurant_external_citation_workspace_provider_observed",
        "restaurant_external_citation_observations",
        ["workspace_id", "provider", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_restaurant_external_citation_workspace_provider_observed",
        table_name="restaurant_external_citation_observations",
    )
    op.drop_index(
        "ix_restaurant_external_citation_observations_workspace_id",
        table_name="restaurant_external_citation_observations",
    )
    op.drop_table("restaurant_external_citation_observations")
    op.drop_index(
        "ix_restaurant_answer_results_workspace_state",
        table_name="restaurant_answer_results",
    )
    op.drop_index(
        "ix_restaurant_answer_results_workspace_id",
        table_name="restaurant_answer_results",
    )
    op.drop_index(
        "ix_restaurant_answer_results_run_id",
        table_name="restaurant_answer_results",
    )
    op.drop_table("restaurant_answer_results")
    op.drop_index(
        "ix_restaurant_answer_runs_workspace_entity_created",
        table_name="restaurant_answer_runs",
    )
    op.drop_index(
        "ix_restaurant_answer_runs_workspace_id",
        table_name="restaurant_answer_runs",
    )
    op.drop_index(
        "ix_restaurant_answer_runs_suite_version_id",
        table_name="restaurant_answer_runs",
    )
    op.drop_table("restaurant_answer_runs")
    op.drop_index(
        "ix_restaurant_answer_suite_versions_workspace_id",
        table_name="restaurant_answer_suite_versions",
    )
    op.drop_table("restaurant_answer_suite_versions")
