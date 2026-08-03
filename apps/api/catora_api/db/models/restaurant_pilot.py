from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class RestaurantPilotAcceptancePlanRecord(Base):
    __tablename__ = "restaurant_pilot_acceptance_plans"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "pilot_key",
            name="uq_restaurant_pilot_plan_workspace_key",
        ),
        UniqueConstraint(
            "workspace_id",
            "plan_sha256",
            name="uq_restaurant_pilot_plan_workspace_sha256",
        ),
        Index(
            "ix_restaurant_pilot_plans_workspace_state",
            "workspace_id",
            "state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    pilot_key: Mapped[str] = mapped_column(String(100), nullable=False)
    client_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    release_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    owners: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    access_grants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    field_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    module_states: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    rollback_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestaurantPilotAcceptanceCheckRecord(Base):
    __tablename__ = "restaurant_pilot_acceptance_checks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "plan_id",
            "check_key",
            name="uq_restaurant_pilot_check_plan_key",
        ),
        Index(
            "ix_restaurant_pilot_checks_workspace_state",
            "workspace_id",
            "state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("restaurant_pilot_acceptance_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    check_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(1_000))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_role: Mapped[str | None] = mapped_column(String(100))
    reviewer_reference: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestaurantPilotAcceptanceDecisionRecord(Base):
    __tablename__ = "restaurant_pilot_acceptance_decisions"
    __table_args__ = (
        Index(
            "ix_restaurant_pilot_decisions_workspace_decided",
            "workspace_id",
            "decided_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("restaurant_pilot_acceptance_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    repository_readiness_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    external_authorization_reference: Mapped[str | None] = mapped_column(String(1_000))
    external_authorization_sha256: Mapped[str | None] = mapped_column(String(64))
    decision_note: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    live_activation_performed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestaurantPilotDisconnectRunRecord(Base):
    __tablename__ = "restaurant_pilot_disconnect_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_restaurant_pilot_disconnect_workspace_idempotency",
        ),
        Index(
            "ix_restaurant_pilot_disconnect_workspace_started",
            "workspace_id",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("restaurant_pilot_acceptance_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_reference: Mapped[str | None] = mapped_column(String(1_000))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    ordering_impact_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deployment_impact_observed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_access_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_access_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
