from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class LocalProfileProviderAccount(Base):
    __tablename__ = "local_profile_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_local_profile_account_workspace_provider_external",
        ),
        Index(
            "ix_local_profile_accounts_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(500))
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LocalProfileObservationRecord(Base):
    __tablename__ = "local_profile_observations"
    __table_args__ = (
        UniqueConstraint(
            "provider_account_id",
            "external_profile_id",
            "observation_hash",
            name="uq_local_profile_observation_account_profile_hash",
        ),
        Index(
            "ix_local_profile_observations_workspace_profile_observed",
            "workspace_id",
            "external_profile_id",
            "observed_at",
        ),
        Index(
            "ix_local_profile_observations_account_current",
            "provider_account_id",
            "is_current",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("local_profile_provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_profile_id: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_location_name: Mapped[str | None] = mapped_column(String(1_000))
    profile_state: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(100))
    website_url: Mapped[str | None] = mapped_column(String(2_000))
    menu_url: Mapped[str | None] = mapped_column(String(2_000))
    ordering_url: Mapped[str | None] = mapped_column(String(2_000))
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latitude: Mapped[str | None] = mapped_column(String(50))
    longitude: Mapped[str | None] = mapped_column(String(50))
    regular_hours: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    special_hours: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    service_areas: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    media_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_fields_present: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BranchLocalProfileLink(Base):
    __tablename__ = "branch_local_profile_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "restaurant_location_id",
            "provider_account_id",
            name="uq_branch_local_profile_link_location_account",
        ),
        UniqueConstraint(
            "workspace_id",
            "provider_account_id",
            "external_profile_id",
            name="uq_branch_local_profile_link_account_profile",
        ),
        Index(
            "ix_branch_local_profile_links_workspace_state",
            "workspace_id",
            "match_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("local_profile_provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_profile_id: Mapped[str] = mapped_column(String(500), nullable=False)
    match_state: Mapped[str] = mapped_column(String(30), nullable=False)
    match_method: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LocalProfileConflictRecord(Base):
    __tablename__ = "local_profile_conflicts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "branch_profile_link_id",
            "field_key",
            "fingerprint",
            name="uq_local_profile_conflict_link_field_fingerprint",
        ),
        Index(
            "ix_local_profile_conflicts_workspace_status_severity",
            "workspace_id",
            "status",
            "severity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    branch_profile_link_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("branch_local_profile_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_profile_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("local_profile_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_key: Mapped[str] = mapped_column(String(160), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    restaurant_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    provider_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
