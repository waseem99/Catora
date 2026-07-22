from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict
LIST_DEFAULT = list


class BuyerIntent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "buyer_intents"
    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('draft','approved','superseded')",
            name="valid_approval_status",
        ),
        UniqueConstraint("workspace_id", "lineage_id", "version"),
        Index(
            "ix_buyer_intents_workspace_lineage_version",
            "workspace_id",
            "lineage_id",
            "version",
        ),
    )
    lineage_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("buyer_intents.id", ondelete="SET NULL"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    structured_intent: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")


class IntentSuite(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "intent_suites"
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class IntentSuiteMember(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "intent_suite_members"
    __table_args__ = (
        CheckConstraint("position >= 0", name="valid_position"),
        UniqueConstraint("intent_suite_id", "position"),
        UniqueConstraint("intent_suite_id", "buyer_intent_id"),
    )
    intent_suite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("intent_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    buyer_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("buyer_intents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class IntentSuiteRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "intent_suite_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed')",
            name="valid_status",
        ),
    )
    intent_suite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("intent_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("intent_suite_runs.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    requested_product_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=LIST_DEFAULT,
    )
    source_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntentRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "intent_runs"
    buyer_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("buyer_intents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    intent_suite_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("intent_suite_runs.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntentProductMatch(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "intent_product_matches"
    __table_args__ = (UniqueConstraint("intent_run_id", "product_id", "variant_id"),)
    intent_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("intent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    explanation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
