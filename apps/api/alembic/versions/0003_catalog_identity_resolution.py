"""add catalog identity resolution

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commercial_product_identities",
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('active','dissolved')",
            name="valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_commercial_product_identities_created_by_user_id"),
        "commercial_product_identities",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_commercial_product_identities_workspace_id"),
        "commercial_product_identities",
        ["workspace_id"],
    )

    op.create_table(
        "product_identity_memberships",
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("link_reason", sa.Text(), nullable=False),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlinked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("unlink_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["commercial_product_identities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unlinked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_identity_memberships_identity_id"),
        "product_identity_memberships",
        ["identity_id"],
    )
    op.create_index(
        op.f("ix_product_identity_memberships_linked_by_user_id"),
        "product_identity_memberships",
        ["linked_by_user_id"],
    )
    op.create_index(
        op.f("ix_product_identity_memberships_product_id"),
        "product_identity_memberships",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_identity_memberships_unlinked_at"),
        "product_identity_memberships",
        ["unlinked_at"],
    )
    op.create_index(
        op.f("ix_product_identity_memberships_unlinked_by_user_id"),
        "product_identity_memberships",
        ["unlinked_by_user_id"],
    )
    op.create_index(
        op.f("ix_product_identity_memberships_workspace_id"),
        "product_identity_memberships",
        ["workspace_id"],
    )
    op.create_index(
        "ix_product_identity_memberships_active_group",
        "product_identity_memberships",
        ["workspace_id", "identity_id"],
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )
    op.create_index(
        "uq_active_product_identity_membership",
        "product_identity_memberships",
        ["workspace_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )

    op.create_table(
        "product_identity_candidates",
        sa.Column("left_product_id", sa.Uuid(), nullable=False),
        sa.Column("right_product_id", sa.Uuid(), nullable=False),
        sa.Column("match_type", sa.String(length=30), nullable=False),
        sa.Column("score_basis_points", sa.Integer(), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
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
            "left_product_id <> right_product_id",
            name="different_products",
        ),
        sa.CheckConstraint(
            "match_type IN ('deterministic','fuzzy')",
            name="valid_match_type",
        ),
        sa.CheckConstraint(
            "score_basis_points >= 0 AND score_basis_points <= 10000",
            name="valid_score",
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','superseded')",
            name="valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["left_product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["right_product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "left_product_id",
            "right_product_id",
            "algorithm_version",
        ),
    )
    op.create_index(
        op.f("ix_product_identity_candidates_left_product_id"),
        "product_identity_candidates",
        ["left_product_id"],
    )
    op.create_index(
        op.f("ix_product_identity_candidates_resolved_by_user_id"),
        "product_identity_candidates",
        ["resolved_by_user_id"],
    )
    op.create_index(
        op.f("ix_product_identity_candidates_right_product_id"),
        "product_identity_candidates",
        ["right_product_id"],
    )
    op.create_index(
        op.f("ix_product_identity_candidates_workspace_id"),
        "product_identity_candidates",
        ["workspace_id"],
    )
    op.create_index(
        "ix_product_identity_candidates_review",
        "product_identity_candidates",
        ["workspace_id", "status", "score_basis_points"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_identity_candidates_review",
        table_name="product_identity_candidates",
    )
    op.drop_index(
        op.f("ix_product_identity_candidates_workspace_id"),
        table_name="product_identity_candidates",
    )
    op.drop_index(
        op.f("ix_product_identity_candidates_right_product_id"),
        table_name="product_identity_candidates",
    )
    op.drop_index(
        op.f("ix_product_identity_candidates_resolved_by_user_id"),
        table_name="product_identity_candidates",
    )
    op.drop_index(
        op.f("ix_product_identity_candidates_left_product_id"),
        table_name="product_identity_candidates",
    )
    op.drop_table("product_identity_candidates")

    op.drop_index(
        "uq_active_product_identity_membership",
        table_name="product_identity_memberships",
    )
    op.drop_index(
        "ix_product_identity_memberships_active_group",
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_workspace_id"),
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_unlinked_by_user_id"),
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_unlinked_at"),
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_product_id"),
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_linked_by_user_id"),
        table_name="product_identity_memberships",
    )
    op.drop_index(
        op.f("ix_product_identity_memberships_identity_id"),
        table_name="product_identity_memberships",
    )
    op.drop_table("product_identity_memberships")

    op.drop_index(
        op.f("ix_commercial_product_identities_workspace_id"),
        table_name="commercial_product_identities",
    )
    op.drop_index(
        op.f("ix_commercial_product_identities_created_by_user_id"),
        table_name="commercial_product_identities",
    )
    op.drop_table("commercial_product_identities")
