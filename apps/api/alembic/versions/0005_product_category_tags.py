"""add product category tags

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_category_tags",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=50), nullable=False),
        sa.Column("assignment_source", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assignment_source IN ('manual','deterministic')",
            name="valid_assignment_source",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "product_id", "category_id"),
    )
    op.create_index(
        op.f("ix_product_category_tags_assigned_by_user_id"),
        "product_category_tags",
        ["assigned_by_user_id"],
    )
    op.create_index(
        op.f("ix_product_category_tags_category_id"),
        "product_category_tags",
        ["category_id"],
    )
    op.create_index(
        op.f("ix_product_category_tags_product_id"),
        "product_category_tags",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_category_tags_workspace_id"),
        "product_category_tags",
        ["workspace_id"],
    )
    op.create_index(
        "ix_product_category_tags_product_version",
        "product_category_tags",
        ["workspace_id", "product_id", "taxonomy_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_category_tags_product_version",
        table_name="product_category_tags",
    )
    op.drop_index(
        op.f("ix_product_category_tags_workspace_id"),
        table_name="product_category_tags",
    )
    op.drop_index(
        op.f("ix_product_category_tags_product_id"),
        table_name="product_category_tags",
    )
    op.drop_index(
        op.f("ix_product_category_tags_category_id"),
        table_name="product_category_tags",
    )
    op.drop_index(
        op.f("ix_product_category_tags_assigned_by_user_id"),
        table_name="product_category_tags",
    )
    op.drop_table("product_category_tags")
