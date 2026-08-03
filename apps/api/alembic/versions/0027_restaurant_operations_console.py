"""Add restaurant operations console reporting and monitoring.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
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
        "operations_console_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("definition_version", sa.String(100), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("section_states", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "snapshot_sha256",
            name="uq_operations_console_snapshot_workspace_sha256",
        ),
    )
    op.create_index(
        "ix_operations_console_snapshots_workspace_generated",
        "operations_console_snapshots",
        ["workspace_id", "generated_at"],
    )

    op.create_table(
        "operations_console_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("alert_key", sa.String(200), nullable=False),
        sa.Column("section_key", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["operations_console_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "fingerprint",
            name="uq_operations_console_alert_workspace_fingerprint",
        ),
    )
    op.create_index(
        "ix_operations_console_alerts_workspace_status_severity",
        "operations_console_alerts",
        ["workspace_id", "status", "severity"],
    )

    op.create_table(
        "operations_console_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("action_key", sa.String(200), nullable=False),
        sa.Column("section_key", sa.String(60), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.String(100), nullable=False),
        sa.Column("verification_method", sa.Text(), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_workflow", sa.String(60), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("direct_mutation_allowed", sa.Boolean(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["operations_console_alerts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "action_key",
            name="uq_operations_console_action_workspace_key",
        ),
    )
    op.create_index(
        "ix_operations_console_actions_workspace_state",
        "operations_console_actions",
        ["workspace_id", "state"],
    )

    op.create_table(
        "operations_monitor_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_key", sa.String(200), nullable=False),
        sa.Column("cadence", sa.String(30), nullable=False),
        sa.Column("section_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_channel", sa.String(30), nullable=False),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            "schedule_key",
            name="uq_operations_monitor_workspace_key",
        ),
    )
    op.create_index(
        "ix_operations_monitor_workspace_enabled_due",
        "operations_monitor_schedules",
        ["workspace_id", "enabled", "next_due_at"],
    )

    op.create_table(
        "operations_monitor_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["operations_monitor_schedules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["operations_console_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_operations_monitor_run_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_operations_monitor_runs_workspace_started",
        "operations_monitor_runs",
        ["workspace_id", "started_at"],
    )

    op.create_table(
        "operations_console_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("export_format", sa.String(20), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sanitized_payload", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["operations_console_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "snapshot_id",
            "export_format",
            "payload_sha256",
            name="uq_operations_console_export_snapshot_format_hash",
        ),
    )
    op.create_index(
        "ix_operations_console_exports_workspace_generated",
        "operations_console_exports",
        ["workspace_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operations_console_exports_workspace_generated",
        table_name="operations_console_exports",
    )
    op.drop_table("operations_console_exports")
    op.drop_index(
        "ix_operations_monitor_runs_workspace_started",
        table_name="operations_monitor_runs",
    )
    op.drop_table("operations_monitor_runs")
    op.drop_index(
        "ix_operations_monitor_workspace_enabled_due",
        table_name="operations_monitor_schedules",
    )
    op.drop_table("operations_monitor_schedules")
    op.drop_index(
        "ix_operations_console_actions_workspace_state",
        table_name="operations_console_actions",
    )
    op.drop_table("operations_console_actions")
    op.drop_index(
        "ix_operations_console_alerts_workspace_status_severity",
        table_name="operations_console_alerts",
    )
    op.drop_table("operations_console_alerts")
    op.drop_index(
        "ix_operations_console_snapshots_workspace_generated",
        table_name="operations_console_snapshots",
    )
    op.drop_table("operations_console_snapshots")
