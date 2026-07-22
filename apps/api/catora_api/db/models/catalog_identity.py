from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class CommercialProductIdentity(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "commercial_product_identities"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','dissolved')",
            name="valid_status",
        ),
    )

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    dissolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductIdentityMembership(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "product_identity_memberships"
    __table_args__ = (
        Index(
            "uq_active_product_identity_membership",
            "workspace_id",
            "product_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
        Index(
            "ix_product_identity_memberships_active_group",
            "workspace_id",
            "identity_id",
            postgresql_where=text("unlinked_at IS NULL"),
        ),
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("commercial_product_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    link_reason: Mapped[str] = mapped_column(Text, nullable=False)
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unlinked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    unlink_reason: Mapped[str | None] = mapped_column(Text)


class ProductIdentityCandidate(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "product_identity_candidates"
    __table_args__ = (
        CheckConstraint("left_product_id <> right_product_id", name="different_products"),
        CheckConstraint(
            "match_type IN ('deterministic','fuzzy')",
            name="valid_match_type",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','superseded')",
            name="valid_status",
        ),
        CheckConstraint(
            "score_basis_points >= 0 AND score_basis_points <= 10000",
            name="valid_score",
        ),
        UniqueConstraint(
            "workspace_id",
            "left_product_id",
            "right_product_id",
            "algorithm_version",
        ),
        Index(
            "ix_product_identity_candidates_review",
            "workspace_id",
            "status",
            "score_basis_points",
        ),
    )

    left_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    right_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_type: Mapped[str] = mapped_column(String(30), nullable=False)
    score_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    signals: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
