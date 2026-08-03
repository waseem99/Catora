from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class MeasurementProviderAccount(Base):
    __tablename__ = "measurement_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "external_account_id",
            name="uq_measurement_account_workspace_provider_external",
        ),
        Index("ix_measurement_accounts_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(500), nullable=False)
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    sync_checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MeasurementPropertyRecord(Base):
    __tablename__ = "measurement_properties"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider_account_id",
            "external_property_id",
            name="uq_measurement_property_account_external",
        ),
        Index("ix_measurement_properties_workspace_status", "workspace_id", "status"),
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
        ForeignKey("measurement_provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_property_id: Mapped[str] = mapped_column(String(500), nullable=False)
    property_type: Mapped[str] = mapped_column(String(60), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(500))
    canonical_origin: Mapped[str | None] = mapped_column(String(2_000))
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MeasurementObservationRecord(Base):
    __tablename__ = "measurement_observations"
    __table_args__ = (
        UniqueConstraint(
            "measurement_property_id",
            "metric_key",
            "dimension_hash",
            "window_start",
            "window_end",
            "observation_hash",
            name="uq_measurement_observation_metric_window_hash",
        ),
        Index(
            "ix_measurement_observations_workspace_metric_window",
            "workspace_id",
            "metric_key",
            "window_start",
            "window_end",
        ),
        Index(
            "ix_measurement_observations_property_freshness",
            "measurement_property_id",
            "observed_at",
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
    measurement_property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("measurement_properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(160), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(100), nullable=False)
    value_microunits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dimensions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    dimension_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_state: Mapped[str] = mapped_column(String(30), nullable=False)
    freshness_state: Mapped[str] = mapped_column(String(30), nullable=False)
    source_definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MeasurementAttributionLink(Base):
    __tablename__ = "measurement_attribution_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "measurement_observation_id",
            "target_type",
            "target_id",
            name="uq_measurement_attribution_observation_target",
        ),
        Index(
            "ix_measurement_attribution_workspace_state",
            "workspace_id",
            "attribution_state",
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
    measurement_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("measurement_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attribution_state: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MeasurementChangeAnnotation(Base):
    __tablename__ = "measurement_change_annotations"
    __table_args__ = (
        Index(
            "ix_measurement_annotations_workspace_occurred",
            "workspace_id",
            "occurred_at",
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
    annotation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
