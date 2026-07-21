"""add incremental audit state

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_runs",
        sa.Column(
            "product_snapshot_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("ck_audit_runs_valid_mode"),
        "audit_runs",
        type_="check",
    )
    op.create_check_constraint(
        "valid_mode",
        "audit_runs",
        "mode IN ('full','incremental')",
    )


def downgrade() -> None:
    op.execute("UPDATE audit_runs SET mode = 'full' WHERE mode = 'incremental'")
    op.drop_constraint(
        op.f("ck_audit_runs_valid_mode"),
        "audit_runs",
        type_="check",
    )
    op.create_check_constraint("valid_mode", "audit_runs", "mode IN ('full')")
    op.drop_column("audit_runs", "product_snapshot_hashes")
