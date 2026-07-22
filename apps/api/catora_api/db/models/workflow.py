from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict


class Recommendation(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "recommendations"
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    audit_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_findings.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_microunits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT, server_default=text("'{}'::jsonb")
    )


class RecommendationJob(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="valid_status",
        ),
        Index(
            "ix_recommendation_jobs_workspace_status_created",
            "workspace_id",
            "status",
            "created_at",
        ),
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    audit_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_findings.id", ondelete="SET NULL"), index=True
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("recommendations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    budget_microunits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    failure_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationField(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_fields"
    __table_args__ = (UniqueConstraint("recommendation_id", "field_key"),)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(150), nullable=False)
    original_value: Mapped[object | None] = mapped_column(JSONB)
    proposed_value: Mapped[object | None] = mapped_column(JSONB)
    edited_value: Mapped[object | None] = mapped_column(JSONB)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proposal_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT, server_default=text("'{}'::jsonb")
    )


class ReviewDecision(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "review_decisions"
    recommendation_field_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recommendation_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class ChangeSet(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "change_sets"
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeSetItem(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "change_set_items"
    __table_args__ = (UniqueConstraint("change_set_id", "recommendation_field_id"),)
    change_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation_field_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("recommendation_fields.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approved_value: Mapped[object | None] = mapped_column(JSONB)


class MarketComparison(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "market_comparisons"
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketConflict(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "market_conflicts"
    market_comparison_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("market_comparisons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(150), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    values: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
