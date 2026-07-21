"""add persisted audit run lifecycle

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "audit_runs",
        "source_snapshot_hash",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.add_column(
        "audit_runs",
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column("audit_runs", sa.Column("previous_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "audit_runs",
        sa.Column(
            "taxonomy_version",
            sa.String(length=50),
            server_default="legacy",
            nullable=False,
        ),
    )
    op.add_column(
        "audit_runs",
        sa.Column("mode", sa.String(length=30), server_default="full", nullable=False),
    )
    op.add_column(
        "audit_runs",
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "audit_runs",
        sa.Column("progress_total", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "audit_runs",
        sa.Column(
            "cancellation_requested",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    for column_name in ("score_summary", "finding_counts", "failure_summary"):
        op.add_column(
            "audit_runs",
            sa.Column(
                column_name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
    op.create_foreign_key(
        op.f("fk_audit_runs_requested_by_user_id_users"),
        "audit_runs",
        "users",
        ["requested_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_audit_runs_previous_run_id_audit_runs"),
        "audit_runs",
        "audit_runs",
        ["previous_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_audit_runs_requested_by_user_id"),
        "audit_runs",
        ["requested_by_user_id"],
    )
    op.create_index(
        op.f("ix_audit_runs_previous_run_id"),
        "audit_runs",
        ["previous_run_id"],
    )
    op.create_check_constraint(
        "valid_status",
        "audit_runs",
        "status IN ('queued','running','completed','failed','cancelled')",
    )
    op.create_check_constraint("valid_mode", "audit_runs", "mode IN ('full')")
    op.create_check_constraint(
        "valid_progress",
        "audit_runs",
        "progress_current >= 0 AND progress_total >= 0 "
        "AND progress_current <= progress_total",
    )

    op.execute("UPDATE audit_findings SET status = 'ongoing' WHERE status = 'open'")
    op.add_column(
        "audit_findings",
        sa.Column("previous_finding_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "field_key",
            sa.String(length=150),
            server_default="legacy",
            nullable=False,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "affected_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "remediation_type",
            sa.String(length=80),
            server_default="review",
            nullable=False,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "failure_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "audit_findings",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_audit_findings_previous_finding_id_audit_findings"),
        "audit_findings",
        "audit_findings",
        ["previous_finding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_audit_findings_previous_finding_id"),
        "audit_findings",
        ["previous_finding_id"],
    )
    op.create_index(
        "ix_audit_findings_run_filters",
        "audit_findings",
        ["workspace_id", "audit_run_id", "status", "severity"],
    )
    op.create_check_constraint(
        "valid_status",
        "audit_findings",
        "status IN ('new','ongoing','regressed','resolved')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_audit_findings_valid_status"),
        "audit_findings",
        type_="check",
    )
    op.drop_index("ix_audit_findings_run_filters", table_name="audit_findings")
    op.drop_index(
        op.f("ix_audit_findings_previous_finding_id"),
        table_name="audit_findings",
    )
    op.drop_constraint(
        op.f("fk_audit_findings_previous_finding_id_audit_findings"),
        "audit_findings",
        type_="foreignkey",
    )
    for column_name in (
        "resolved_at",
        "last_seen_at",
        "first_seen_at",
        "failure_codes",
        "remediation_type",
        "affected_value",
        "field_key",
        "previous_finding_id",
    ):
        op.drop_column("audit_findings", column_name)

    op.drop_constraint(op.f("ck_audit_runs_valid_progress"), "audit_runs", type_="check")
    op.drop_constraint(op.f("ck_audit_runs_valid_mode"), "audit_runs", type_="check")
    op.drop_constraint(op.f("ck_audit_runs_valid_status"), "audit_runs", type_="check")
    op.drop_index(op.f("ix_audit_runs_previous_run_id"), table_name="audit_runs")
    op.drop_index(op.f("ix_audit_runs_requested_by_user_id"), table_name="audit_runs")
    op.drop_constraint(
        op.f("fk_audit_runs_previous_run_id_audit_runs"),
        "audit_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_audit_runs_requested_by_user_id_users"),
        "audit_runs",
        type_="foreignkey",
    )
    for column_name in (
        "failure_summary",
        "finding_counts",
        "score_summary",
        "cancellation_requested",
        "progress_total",
        "progress_current",
        "mode",
        "taxonomy_version",
        "previous_run_id",
        "requested_by_user_id",
    ):
        op.drop_column("audit_runs", column_name)
    op.execute(
        "UPDATE audit_runs SET source_snapshot_hash = repeat('0', 64) "
        "WHERE source_snapshot_hash IS NULL"
    )
    op.alter_column(
        "audit_runs",
        "source_snapshot_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
