from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class AuthorityProviderAccount(Base):
    __tablename__ = "authority_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_authority_account_workspace_provider_external",
        ),
        Index("ix_authority_accounts_workspace_status", "workspace_id", "status"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthorityObservationRecord(Base):
    __tablename__ = "authority_observations"
    __table_args__ = (
        UniqueConstraint(
            "provider_account_id",
            "external_observation_id",
            "observation_hash",
            name="uq_authority_observation_account_external_hash",
        ),
        Index(
            "ix_authority_observations_workspace_type_observed",
            "workspace_id",
            "observation_type",
            "observed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("authority_provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_observation_id: Mapped[str] = mapped_column(String(500), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(500))
    anchor_or_mention_text: Mapped[str | None] = mapped_column(Text)
    provider_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    identity_state: Mapped[str] = mapped_column(String(30), nullable=False)
    identity_method: Mapped[str] = mapped_column(String(100), nullable=False)
    link_state: Mapped[str] = mapped_column(String(30), nullable=False)
    nofollow: Mapped[bool | None]
    sponsored: Mapped[bool | None]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthorityOpportunityRecord(Base):
    __tablename__ = "authority_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "opportunity_fingerprint",
            name="uq_authority_opportunity_workspace_fingerprint",
        ),
        Index(
            "ix_authority_opportunities_workspace_state_score",
            "workspace_id",
            "state",
            "score_basis_points",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    authority_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("authority_observations.id", ondelete="SET NULL")
    )
    opportunity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    risk_state: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str] = mapped_column(Text, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    score_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    score_version: Mapped[str] = mapped_column(String(100), nullable=False)
    opportunity_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthoritySuppressionRecord(Base):
    __tablename__ = "authority_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "normalized_target",
            name="uq_authority_suppression_workspace_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    normalized_target: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthorityOutreachDraftRecord(Base):
    __tablename__ = "authority_outreach_drafts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "opportunity_id",
            "draft_version",
            name="uq_authority_outreach_workspace_opportunity_version",
        ),
        Index("ix_authority_outreach_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("authority_opportunities.id", ondelete="CASCADE"), nullable=False
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    factual_claims: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    suppression_checked: Mapped[bool] = mapped_column(nullable=False)
    legal_basis_confirmed: Mapped[bool] = mapped_column(nullable=False)
    generated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthorityOutreachDecisionRecord(Base):
    __tablename__ = "authority_outreach_decisions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "draft_id",
            name="uq_authority_outreach_decision_workspace_draft",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("authority_outreach_drafts.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
