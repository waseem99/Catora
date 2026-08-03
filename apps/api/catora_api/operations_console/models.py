from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

OPERATIONS_CONSOLE_VERSION: Literal["restaurant-operations-console/v1"] = (
    "restaurant-operations-console/v1"
)
OPERATIONS_EXPORT_VERSION: Literal["restaurant-operations-export/v1"] = (
    "restaurant-operations-export/v1"
)

ConsoleSectionKey = Literal[
    "catalog_freshness",
    "technical_seo",
    "answer_readiness",
    "local_profiles",
    "reputation",
    "measurement",
    "authority",
    "publishing",
]
ConsoleSectionState = Literal[
    "current",
    "partial",
    "stale",
    "unavailable",
    "disconnected",
    "blocked",
]
AlertSeverity = Literal["critical", "high", "medium", "low", "informational"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
ActionState = Literal["proposed", "approved", "rejected", "completed", "blocked"]
MonitorCadence = Literal["hourly", "daily", "weekly", "monthly"]
MonitorRunStatus = Literal["running", "completed", "failed", "skipped"]
ExportFormat = Literal["json", "csv"]


class OperationsConsoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConsoleMetric(OperationsConsoleModel):
    key: str = Field(pattern=r"^[a-z0-9_.]{2,160}$")
    label: str = Field(min_length=1, max_length=200)
    value: int | float | str | bool | None
    unit: str | None = Field(default=None, max_length=50)
    definition_version: str = Field(min_length=1, max_length=100)
    source_coverage: str = Field(min_length=1, max_length=500)
    window_start: datetime | None = None
    window_end: datetime | None = None
    observed_at: datetime | None = None
    source_references: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_metric(self) -> ConsoleMetric:
        for name, value in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("observed_at", self.observed_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end <= self.window_start
        ):
            raise ValueError("Metric window_end must be later than window_start")
        return self


class ConsoleSection(OperationsConsoleModel):
    key: ConsoleSectionKey
    state: ConsoleSectionState
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    metrics: tuple[ConsoleMetric, ...] = Field(default=(), max_length=100)
    evidence_references: tuple[str, ...] = Field(default=(), max_length=100)
    observed_at: datetime | None = None
    stale_after: datetime | None = None
    unavailable_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_section(self) -> ConsoleSection:
        if self.state in {"unavailable", "disconnected", "blocked"}:
            if not self.unavailable_reason:
                raise ValueError("Unavailable sections require an explicit reason")
            if any(metric.value is not None for metric in self.metrics):
                raise ValueError("Unavailable sections cannot expose synthetic values")
        for name, value in (
            ("observed_at", self.observed_at),
            ("stale_after", self.stale_after),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"Section {name} must be timezone-aware")
        return self


class RestaurantConsoleSnapshot(OperationsConsoleModel):
    version: Literal["restaurant-operations-console/v1"] = OPERATIONS_CONSOLE_VERSION
    workspace_id: UUID
    brand_id: UUID | None = None
    location_id: UUID | None = None
    generated_at: datetime
    sections: tuple[ConsoleSection, ...] = Field(min_length=1, max_length=20)
    available_section_count: int = Field(ge=0)
    stale_section_count: int = Field(ge=0)
    unavailable_section_count: int = Field(ge=0)
    critical_alert_count: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    causal_claim_allowed: Literal[False] = False
    direct_mutation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_counts(self) -> RestaurantConsoleSnapshot:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if len({section.key for section in self.sections}) != len(self.sections):
            raise ValueError("Console section keys must be unique")
        expected_available = sum(
            section.state in {"current", "partial"} for section in self.sections
        )
        expected_stale = sum(section.state == "stale" for section in self.sections)
        expected_unavailable = sum(
            section.state in {"unavailable", "disconnected", "blocked"}
            for section in self.sections
        )
        if (
            self.available_section_count != expected_available
            or self.stale_section_count != expected_stale
            or self.unavailable_section_count != expected_unavailable
        ):
            raise ValueError("Console section counts do not reconcile")
        return self


class ConsoleAlert(OperationsConsoleModel):
    alert_key: str = Field(pattern=r"^[a-z0-9_.:-]{3,200}$")
    severity: AlertSeverity
    status: AlertStatus = "open"
    title: str = Field(min_length=1, max_length=500)
    detail: str = Field(min_length=1, max_length=2_000)
    section_key: ConsoleSectionKey
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=100)
    detected_at: datetime
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_detected_at(self) -> ConsoleAlert:
        if self.detected_at.tzinfo is None:
            raise ValueError("Alert detected_at must be timezone-aware")
        return self


class ConsoleActionProposal(OperationsConsoleModel):
    action_key: str = Field(pattern=r"^[a-z0-9_.:-]{3,200}$")
    section_key: ConsoleSectionKey
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2_000)
    owner_role: str = Field(min_length=1, max_length=100)
    verification_method: str = Field(min_length=1, max_length=1_000)
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=100)
    target_workflow: Literal[
        "change_set",
        "git_proposal",
        "local_profile_review",
        "review_response_draft",
        "authority_outreach_draft",
        "provider_connection",
        "manual_review",
    ]
    state: ActionState = "proposed"
    direct_mutation_allowed: Literal[False] = False


class MonitorSchedule(OperationsConsoleModel):
    schedule_key: str = Field(pattern=r"^[a-z0-9_.:-]{3,200}$")
    cadence: MonitorCadence
    section_keys: tuple[ConsoleSectionKey, ...] = Field(min_length=1, max_length=20)
    timezone: str = Field(min_length=1, max_length=100)
    enabled: bool = False
    next_due_at: datetime | None = None
    notification_channel: Literal["none", "in_app", "email"] = "none"
    notification_enabled: bool = False

    @model_validator(mode="after")
    def validate_schedule(self) -> MonitorSchedule:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Monitor timezone is unknown") from exc
        if len(set(self.section_keys)) != len(self.section_keys):
            raise ValueError("Monitor section keys must be unique")
        if self.next_due_at is not None and self.next_due_at.tzinfo is None:
            raise ValueError("next_due_at must be timezone-aware")
        if self.notification_enabled and not self.enabled:
            raise ValueError("Notifications require an enabled monitor")
        if self.notification_enabled and self.notification_channel == "none":
            raise ValueError("Enabled notifications require an explicit channel")
        return self


class MonitorRunSummary(OperationsConsoleModel):
    status: MonitorRunStatus
    schedule_key: str
    started_at: datetime
    completed_at: datetime | None = None
    snapshot_id: UUID | None = None
    generated_alert_count: int = Field(default=0, ge=0)
    generated_action_count: int = Field(default=0, ge=0)
    failure_code: str | None = Field(default=None, max_length=100)


class OperationsExportBundle(OperationsConsoleModel):
    schema_version: Literal["restaurant-operations-export/v1"] = OPERATIONS_EXPORT_VERSION
    snapshot_id: UUID
    export_format: ExportFormat
    content_type: str
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1, le=5 * 1024 * 1024)
    generated_at: datetime
    sanitized_payload: str
    contains_secrets: Literal[False] = False
    contains_personal_data: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    direct_mutation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_bundle(self) -> OperationsExportBundle:
        if self.generated_at.tzinfo is None:
            raise ValueError("Export generated_at must be timezone-aware")
        if len(self.sanitized_payload.encode("utf-8")) != self.byte_size:
            raise ValueError("Export byte_size does not reconcile")
        return self
