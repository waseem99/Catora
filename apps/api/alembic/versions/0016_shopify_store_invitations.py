"""add Shopify store invitations

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopify_store_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("activated_workspace_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("prospect_name", sa.String(length=200), nullable=False),
        sa.Column("feature_tier", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feature_tier IN ('demo','plus_demo')",
            name=op.f("ck_shopify_store_invitations_valid_feature_tier"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','activated','revoked','expired')",
            name=op.f("ck_shopify_store_invitations_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["activated_workspace_id"],
            ["workspaces.id"],
            name=op.f(
                "fk_shopify_store_invitations_activated_workspace_id_workspaces"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_shopify_store_invitations_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_shopify_store_invitations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopify_store_invitations")),
        sa.UniqueConstraint(
            "shop_domain",
            name=op.f("uq_shopify_store_invitations_shop_domain"),
        ),
    )
    op.create_index(
        op.f("ix_shopify_store_invitations_workspace_id"),
        "shopify_store_invitations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shopify_store_invitations_activated_workspace_id"),
        "shopify_store_invitations",
        ["activated_workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shopify_store_invitations_created_by_user_id"),
        "shopify_store_invitations",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shopify_store_invitations_expires_at"),
        "shopify_store_invitations",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shopify_store_invitations_expires_at"),
        table_name="shopify_store_invitations",
    )
    op.drop_index(
        op.f("ix_shopify_store_invitations_created_by_user_id"),
        table_name="shopify_store_invitations",
    )
    op.drop_index(
        op.f("ix_shopify_store_invitations_activated_workspace_id"),
        table_name="shopify_store_invitations",
    )
    op.drop_index(
        op.f("ix_shopify_store_invitations_workspace_id"),
        table_name="shopify_store_invitations",
    )
    op.drop_table("shopify_store_invitations")
