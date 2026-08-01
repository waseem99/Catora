from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class ReviewProviderAccount(Base):
    __tablename__ = "review_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_review_provider_account_workspace_provider_external",
        ),
        Index("ix_review_accounts_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(500), nullable=False)
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    sync_checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReviewObservationRecord(Base):
    __tablename__ = "review_observations"
    __table_args__ = (
        UniqueConstraint(
            "provider_account_id",
            "external_review_id",
            "observation_hash",
            name="uq_review_observation_account_review_hash",
        ),
        Index(
            "ix_review_observations_workspace_location_created",
            "workspace_id",
            "restaurant_location_id",
            "review_created_at",
        ),
        Index(
            "ix_review_observations_account_current",
            "provider_account_id",
            "is_current",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("review_provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("restaurant_locations.id", ondelete="SET NULL")
    )
    external_location_id: Mapped[str | None] = mapped_column(String(500))
    external_review_id: Mapped[str] = mapped_column(String(500), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))
    reviewer_display_name: Mapped[str | None] = mapped_column(String(300))
    provider_response_text: Mapped[str | None] = mapped_column(Text)
    provider_response_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_state: Mapped[str] = mapped_column(String(30), nullable=False)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewAnalysisRecord(Base):
    __tablename__ = "review_analyses"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "review_observation_id",
            "analysis_version",
            name="uq_review_analysis_observation_version",
        ),
        Index(
            "ix_review_analyses_workspace_risk",
            "workspace_id",
            "risk_level",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    review_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("review_observations.id", ondelete="CASCADE"), nullable=False
    )
    analysis_version: Mapped[str] = mapped_column(String(100), nullable=False)
    themes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    praise: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    concerns: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    escalation_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewResponseDraftRecord(Base):
    __tablename__ = "review_response_drafts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "review_observation_id",
            "draft_version",
            name="uq_review_response_draft_observation_version",
        ),
        Index(
            "ix_review_response_drafts_workspace_status",
            "workspace_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    review_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("review_observations.id", ondelete="CASCADE"), nullable=False
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    edited_text: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
