"""add immutable audit finding market snapshots

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_findings",
        sa.Column(
            "market_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE audit_findings AS finding
        SET market_codes = COALESCE(
            (
                SELECT jsonb_agg(DISTINCT market.code ORDER BY market.code)
                FROM evidence_references AS evidence
                JOIN source_records AS source_record
                  ON source_record.id = evidence.source_record_id
                JOIN catalog_sources AS source
                  ON source.id = source_record.catalog_source_id
                JOIN markets AS market
                  ON market.storefront_id = source.storefront_id
                WHERE evidence.product_id = finding.product_id
                  AND evidence.workspace_id = finding.workspace_id
                  AND source_record.workspace_id = finding.workspace_id
                  AND source.workspace_id = finding.workspace_id
                  AND market.workspace_id = finding.workspace_id
            ),
            '[]'::jsonb
        )
        """
    )
    op.create_index(
        "ix_audit_findings_market_codes",
        "audit_findings",
        ["market_codes"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_audit_findings_market_codes", table_name="audit_findings")
    op.drop_column("audit_findings", "market_codes")
