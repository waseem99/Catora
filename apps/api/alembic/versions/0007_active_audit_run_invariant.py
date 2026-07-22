"""enforce one active audit run per workspace

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX_NAME = "uq_audit_runs_active_workspace"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "audit_runs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="audit_runs")
