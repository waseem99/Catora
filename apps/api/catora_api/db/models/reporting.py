from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict


class ReportJob(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "report_jobs"
    report_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    template_version: Mapped[str] = mapped_column(String(100), nullable=False)


class ExportArtifact(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "export_artifacts"
    report_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("report_jobs.id", ondelete="SET NULL"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)


class MeasurementBaseline(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "measurement_baselines"
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_definitions: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    source_notes: Mapped[str | None] = mapped_column(Text)


class ProductCohort(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "product_cohorts"
    measurement_baseline_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("measurement_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(30), nullable=False)
    membership_snapshot: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditEvent(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "audit_events"
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=JSON_DEFAULT)
