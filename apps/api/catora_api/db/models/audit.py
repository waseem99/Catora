from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict
LIST_DEFAULT = list


class RuleDefinition(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "rule_definitions"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    key: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class RuleVersion(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_definition_id", "version"),)
    rule_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rule_definitions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    specification: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditRun(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "audit_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="valid_status",
        ),
        CheckConstraint("mode IN ('full','incremental')", name="valid_mode"),
        CheckConstraint(
            "progress_current >= 0 AND progress_total >= 0 "
            "AND progress_current <= progress_total",
            name="valid_progress",
        ),
        Index(
            "uq_audit_runs_active_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_runs.id", ondelete="SET NULL"), index=True
    )
    taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="full")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    source_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    product_snapshot_hashes: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    rule_version_set: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=LIST_DEFAULT
    )
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    score_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    finding_counts: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    failure_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=JSON_DEFAULT
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditFinding(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "audit_findings"
    __table_args__ = (
        UniqueConstraint("audit_run_id", "fingerprint"),
        CheckConstraint(
            "severity IN ('critical','high','medium','low','informational')",
            name="valid_severity",
        ),
        CheckConstraint(
            "status IN ('new','ongoing','regressed','resolved')",
            name="valid_status",
        ),
        Index(
            "ix_audit_findings_run_query",
            "workspace_id",
            "audit_run_id",
            "category_key",
            "field_key",
            "remediation_type",
        ),
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_findings.id", ondelete="SET NULL"), index=True
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rule_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    category_key: Mapped[str] = mapped_column(
        String(150), nullable=False, default="unknown", server_default="unknown"
    )
    field_key: Mapped[str] = mapped_column(String(150), nullable=False)
    affected_value: Mapped[
        dict[str, object] | list[object] | str | int | float | bool | None
    ] = mapped_column(JSONB)
    business_impact: Mapped[str] = mapped_column(String(50), nullable=False)
    remediation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    failure_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=LIST_DEFAULT
    )
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
