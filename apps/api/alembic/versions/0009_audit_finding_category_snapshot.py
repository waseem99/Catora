"""add immutable audit finding category snapshot

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_findings",
        sa.Column(
            "category_key",
            sa.String(length=150),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE audit_findings AS finding
        SET category_key = category.key
        FROM products AS product
        JOIN categories AS category ON category.id = product.primary_category_id
        WHERE finding.product_id = product.id
        """
    )
    op.create_index(
        "ix_audit_findings_run_query",
        "audit_findings",
        [
            "workspace_id",
            "audit_run_id",
            "category_key",
            "field_key",
            "remediation_type",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_findings_run_query", table_name="audit_findings")
    op.drop_column("audit_findings", "category_key")
