"""Add generic restaurant pilot production acceptance records.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "restaurant_pilot_acceptance_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pilot_key", sa.String(100), nullable=False),
        sa.Column("client_reference", sa.String(200), nullable=False),
        sa.Column("environment", sa.String(30), nullable=False),
        sa.Column("contract_version", sa.String(100), nullable=False),
        sa.Column("release_revision", sa.String(40), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("owners", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_grants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("module_states", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rollback_contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "pilot_key",
            name="uq_restaurant_pilot_plan_workspace_key",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "plan_sha256",
            name="uq_restaurant_pilot_plan_workspace_sha256",
        ),
    )
    op.create_index(
        "ix_restaurant_pilot_plans_workspace_state",
        "restaurant_pilot_acceptance_plans",
        ["workspace_id", "state"],
    )

    op.create_table(
        "restaurant_pilot_acceptance_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("check_key", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("evidence_reference", sa.String(1000), nullable=True),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_role", sa.String(100), nullable=True),
        sa.Column("reviewer_reference", sa.String(500), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["restaurant_pilot_acceptance_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "plan_id",
            "check_key",
            name="uq_restaurant_pilot_check_plan_key",
        ),
    )
    op.create_index(
        "ix_restaurant_pilot_checks_workspace_state",
        "restaurant_pilot_acceptance_checks",
        ["workspace_id", "state"],
    )

    op.create_table(
        "restaurant_pilot_acceptance_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("repository_readiness_sha256", sa.String(64), nullable=False),
        sa.Column("external_authorization_reference", sa.String(1000), nullable=True),
        sa.Column("external_authorization_sha256", sa.String(64), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("live_activation_performed", sa.Boolean(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["restaurant_pilot_acceptance_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_restaurant_pilot_decisions_workspace_decided",
        "restaurant_pilot_acceptance_decisions",
        ["workspace_id", "decided_at"],
    )

    op.create_table(
        "restaurant_pilot_disconnect_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_reference", sa.String(1000), nullable=True),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("ordering_impact_observed", sa.Boolean(), nullable=False),
        sa.Column("deployment_impact_observed", sa.Boolean(), nullable=False),
        sa.Column("source_access_revoked", sa.Boolean(), nullable=False),
        sa.Column("provider_access_revoked", sa.Boolean(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["restaurant_pilot_acceptance_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_restaurant_pilot_disconnect_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_restaurant_pilot_disconnect_workspace_started",
        "restaurant_pilot_disconnect_runs",
        ["workspace_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_restaurant_pilot_disconnect_workspace_started",
        table_name="restaurant_pilot_disconnect_runs",
    )
    op.drop_table("restaurant_pilot_disconnect_runs")
    op.drop_index(
        "ix_restaurant_pilot_decisions_workspace_decided",
        table_name="restaurant_pilot_acceptance_decisions",
    )
    op.drop_table("restaurant_pilot_acceptance_decisions")
    op.drop_index(
        "ix_restaurant_pilot_checks_workspace_state",
        table_name="restaurant_pilot_acceptance_checks",
    )
    op.drop_table("restaurant_pilot_acceptance_checks")
    op.drop_index(
        "ix_restaurant_pilot_plans_workspace_state",
        table_name="restaurant_pilot_acceptance_plans",
    )
    op.drop_table("restaurant_pilot_acceptance_plans")
