from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from catora_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

JSON_DEFAULT = dict


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
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version_set: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
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
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False, index=True
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
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    business_impact: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
