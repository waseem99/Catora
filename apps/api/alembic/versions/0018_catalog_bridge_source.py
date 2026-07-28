"""allow push-only catalog bridge sources

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("valid_source_type", "catalog_sources", type_="check")
    op.create_check_constraint(
        "valid_source_type",
        "catalog_sources",
        "source_type IN ('shopify','csv','sitemap','urls','bridge')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE catalog_sources SET deleted_at = now(), status = 'invalid' "
            "WHERE source_type = 'bridge' AND deleted_at IS NULL"
        )
    )
    op.drop_constraint("valid_source_type", "catalog_sources", type_="check")
    op.create_check_constraint(
        "valid_source_type",
        "catalog_sources",
        "source_type IN ('shopify','csv','sitemap','urls')",
    )
