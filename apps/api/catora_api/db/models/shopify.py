from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
)


class ShopifyStoreInvitation(
    UUIDPrimaryKeyMixin,
    WorkspaceScopedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "shopify_store_invitations"
    __table_args__ = (
        UniqueConstraint("shop_domain"),
        CheckConstraint(
            "status IN ('pending','activated','revoked','expired')",
            name="valid_status",
        ),
        CheckConstraint(
            "feature_tier IN ('demo','plus_demo')",
            name="valid_feature_tier",
        ),
    )

    activated_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    prospect_name: Mapped[str] = mapped_column(String(200), nullable=False)
    feature_tier: Mapped[str] = mapped_column(
        String(30), nullable=False, default="demo"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
