from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuditRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
AuditRunMode = Literal["full", "incremental"]
FindingStatus = Literal["new", "ongoing", "regressed", "resolved"]
Severity = Literal["critical", "high", "medium", "low", "informational"]


class AuditRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy_version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    mode: AuditRunMode = "full"


class AuditRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    requested_by_user_id: uuid.UUID | None
    previous_run_id: uuid.UUID | None
    taxonomy_version: str
    mode: AuditRunMode
    status: AuditRunStatus
    source_snapshot_hash: str | None
    rule_version_set: list[str]
    progress_current: int = Field(ge=0)
    progress_total: int = Field(ge=0)
    cancellation_requested: bool
    score_summary: dict[str, object]
    finding_counts: dict[str, object]
    failure_summary: dict[str, object]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditFindingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_run_id: uuid.UUID
    previous_finding_id: uuid.UUID | None
    rule_version_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    severity: Severity
    title: str
    explanation: str
    fingerprint: str = Field(min_length=64, max_length=64)
    status: FindingStatus
    field_key: str
    affected_value: dict[str, object] | list[object] | str | int | float | bool | None
    business_impact: str
    remediation_type: str
    failure_codes: list[str]
    evidence: list[dict[str, object]]
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
