"""add append-only recommendation job retry lineage

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
        "recommendation_jobs",
        sa.Column("retry_of_job_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "recommendation_jobs",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_foreign_key(
        op.f("fk_recommendation_jobs_retry_of_job_id_recommendation_jobs"),
        "recommendation_jobs",
        "recommendation_jobs",
        ["retry_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        op.f("uq_recommendation_jobs_retry_of_job_id"),
        "recommendation_jobs",
        ["retry_of_job_id"],
    )
    op.create_check_constraint(
        op.f("ck_recommendation_jobs_valid_retry_count"),
        "recommendation_jobs",
        "retry_count >= 0",
    )
    op.create_index(
        op.f("ix_recommendation_jobs_retry_of_job_id"),
        "recommendation_jobs",
        ["retry_of_job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recommendation_jobs_retry_of_job_id"),
        table_name="recommendation_jobs",
    )
    op.drop_constraint(
        op.f("ck_recommendation_jobs_valid_retry_count"),
        "recommendation_jobs",
        type_="check",
    )
    op.drop_constraint(
        op.f("uq_recommendation_jobs_retry_of_job_id"),
        "recommendation_jobs",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_recommendation_jobs_retry_of_job_id_recommendation_jobs"),
        "recommendation_jobs",
        type_="foreignkey",
    )
    op.drop_column("recommendation_jobs", "retry_count")
    op.drop_column("recommendation_jobs", "retry_of_job_id")
