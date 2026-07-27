"""track the latest ingestion job that observed each source record

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_records",
        sa.Column("last_seen_job_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_source_records_last_seen_job_id_ingestion_jobs"),
        "source_records",
        "ingestion_jobs",
        ["last_seen_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_source_records_last_seen_job_id"),
        "source_records",
        ["last_seen_job_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "UPDATE source_records "
            "SET last_seen_job_id = ingestion_job_id "
            "WHERE last_seen_job_id IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_records_last_seen_job_id"),
        table_name="source_records",
    )
    op.drop_constraint(
        op.f("fk_source_records_last_seen_job_id_ingestion_jobs"),
        "source_records",
        type_="foreignkey",
    )
    op.drop_column("source_records", "last_seen_job_id")
