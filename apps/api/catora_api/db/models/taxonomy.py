from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class ProductCategoryTag(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "product_category_tags"
    __table_args__ = (
        UniqueConstraint("workspace_id", "product_id", "category_id"),
        CheckConstraint(
            "assignment_source IN ('manual','deterministic')",
            name="valid_assignment_source",
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    assignment_source: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
