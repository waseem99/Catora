from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base


class OperationsConsoleSnapshotRecord(Base):
    __tablename__ = "operations_console_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "snapshot_sha256",
            name="uq_operations_console_snapshot_workspace_sha256",
        ),
        Index(
            "ix_operations_console_snapshots_workspace_generated",
            "workspace_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    definition_version: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    section_states: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationsConsoleAlertRecord(Base):
    __tablename__ = "operations_console_alerts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "fingerprint",
            name="uq_operations_console_alert_workspace_fingerprint",
        ),
        Index(
            "ix_operations_console_alerts_workspace_status_severity",
            "workspace_id",
            "status",
            "severity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operations_console_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_key: Mapped[str] = mapped_column(String(200), nullable=False)
    section_key: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationsConsoleActionRecord(Base):
    __tablename__ = "operations_console_actions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "action_key",
            name="uq_operations_console_action_workspace_key",
        ),
        Index(
            "ix_operations_console_actions_workspace_state",
            "workspace_id",
            "state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("operations_console_alerts.id", ondelete="SET NULL")
    )
    action_key: Mapped[str] = mapped_column(String(200), nullable=False)
    section_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(100), nullable=False)
    verification_method: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    target_workflow: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    direct_mutation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationsMonitorScheduleRecord(Base):
    __tablename__ = "operations_monitor_schedules"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "schedule_key",
            name="uq_operations_monitor_workspace_key",
        ),
        Index(
            "ix_operations_monitor_workspace_enabled_due",
            "workspace_id",
            "enabled",
            "next_due_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    schedule_key: Mapped[str] = mapped_column(String(200), nullable=False)
    cadence: Mapped[str] = mapped_column(String(30), nullable=False)
    section_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_channel: Mapped[str] = mapped_column(String(30), nullable=False)
    notification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OperationsMonitorRunRecord(Base):
    __tablename__ = "operations_monitor_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_operations_monitor_run_workspace_idempotency",
        ),
        Index(
            "ix_operations_monitor_runs_workspace_started",
            "workspace_id",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operations_monitor_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("operations_console_snapshots.id", ondelete="SET NULL")
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    failure_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationsConsoleExportRecord(Base):
    __tablename__ = "operations_console_exports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "snapshot_id",
            "export_format",
            "payload_sha256",
            name="uq_operations_console_export_snapshot_format_hash",
        ),
        Index(
            "ix_operations_console_exports_workspace_generated",
            "workspace_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operations_console_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    export_format: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sanitized_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
