from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from catora_api.config import Settings
from catora_api.operations_console import (
    ConsoleMetric,
    ConsoleSection,
    MonitorSchedule,
    compose_console_snapshot,
    derive_console_alerts,
    propose_console_actions,
    render_operations_export,
)

NOW = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
WORKSPACE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SNAPSHOT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _metric(key: str, value: int = 1) -> ConsoleMetric:
    return ConsoleMetric(
        key=key,
        label=key.replace(".", " "),
        value=value,
        unit="count",
        definition_version="restaurant-operations-metric/v1",
        source_coverage="workspace-scoped persisted evidence only",
        observed_at=NOW,
        source_references=(f"metric:{key}",),
    )


def test_snapshot_counts_and_freshness_reconcile() -> None:
    snapshot = compose_console_snapshot(
        workspace_id=WORKSPACE_ID,
        generated_at=NOW,
        sections=(
            ConsoleSection(
                key="catalog_freshness",
                state="current",
                title="Catalog freshness",
                summary="Current facts",
                metrics=(_metric("catalog.fact_count"),),
                observed_at=NOW - timedelta(days=8),
                stale_after=NOW - timedelta(days=1),
            ),
            ConsoleSection(
                key="measurement",
                state="unavailable",
                title="Measurement",
                summary="No provider",
                unavailable_reason="No provider account is configured.",
            ),
        ),
    )
    assert snapshot.stale_section_count == 1
    assert snapshot.unavailable_section_count == 1
    assert snapshot.available_section_count == 0
    assert snapshot.causal_claim_allowed is False
    assert snapshot.direct_mutation_allowed is False


def test_unavailable_sections_cannot_present_synthetic_values() -> None:
    with pytest.raises(ValidationError, match="cannot expose synthetic values"):
        ConsoleSection(
            key="local_profiles",
            state="unavailable",
            title="Local profiles",
            summary="Unavailable",
            unavailable_reason="Provider unavailable",
            metrics=(_metric("local.profile_count", 0),),
        )


def test_alerts_and_actions_are_evidence_backed_and_non_mutating() -> None:
    section = ConsoleSection(
        key="local_profiles",
        state="blocked",
        title="Local profiles",
        summary="Blocked",
        unavailable_reason="Identity conflicts require review.",
        evidence_references=("table:local_profile_conflicts",),
    )
    alerts = derive_console_alerts((section,), detected_at=NOW)
    assert alerts[0].severity == "critical"
    assert alerts[0].evidence_references == ("table:local_profile_conflicts",)
    actions = propose_console_actions(alerts)
    assert actions[0].target_workflow == "local_profile_review"
    assert actions[0].direct_mutation_allowed is False


def test_exports_are_bounded_sanitized_and_non_causal() -> None:
    snapshot = compose_console_snapshot(
        workspace_id=WORKSPACE_ID,
        generated_at=NOW,
        sections=(
            ConsoleSection(
                key="measurement",
                state="current",
                title="Measurement",
                summary="Aggregate observations only",
                metrics=(_metric("measurement.observations", 12),),
                observed_at=NOW,
                stale_after=NOW + timedelta(days=3),
            ),
        ),
    )
    json_bundle = render_operations_export(
        snapshot,
        snapshot_id=SNAPSHOT_ID,
        export_format="json",
        generated_at=NOW,
    )
    csv_bundle = render_operations_export(
        snapshot,
        snapshot_id=SNAPSHOT_ID,
        export_format="csv",
        generated_at=NOW,
    )
    assert json_bundle.snapshot_id == SNAPSHOT_ID
    assert json_bundle.contains_secrets is False
    assert json_bundle.contains_personal_data is False
    assert json_bundle.causal_claim_allowed is False
    assert csv_bundle.sanitized_payload.startswith("section_key,section_state")
    assert csv_bundle.byte_size == len(csv_bundle.sanitized_payload.encode("utf-8"))


def test_export_rejects_restricted_field_names() -> None:
    snapshot = compose_console_snapshot(
        workspace_id=WORKSPACE_ID,
        generated_at=NOW,
        sections=(
            ConsoleSection(
                key="publishing",
                state="partial",
                title="Publishing",
                summary="Review required",
                metrics=(
                    ConsoleMetric(
                        key="publishing.pending",
                        label="Pending",
                        value=1,
                        unit="count",
                        definition_version="restaurant-operations-metric/v1",
                        source_coverage="credential_reference",
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="restricted fields"):
        render_operations_export(
            snapshot,
            snapshot_id=SNAPSHOT_ID,
            export_format="json",
            generated_at=NOW,
        )


def test_monitor_schedule_requires_real_timezone_and_explicit_notification_state() -> None:
    schedule = MonitorSchedule(
        schedule_key="restaurant.daily",
        cadence="daily",
        section_keys=("catalog_freshness", "measurement"),
        timezone="Asia/Karachi",
        enabled=True,
        next_due_at=NOW,
        notification_channel="in_app",
        notification_enabled=True,
    )
    assert schedule.cadence == "daily"
    with pytest.raises(ValidationError, match="unknown"):
        schedule.model_copy(update={"timezone": "Mars/Olympus"}, deep=True).__class__(
            **schedule.model_dump(exclude={"timezone"}),
            timezone="Mars/Olympus",
        )
    with pytest.raises(ValidationError, match="require an enabled monitor"):
        MonitorSchedule(
            schedule_key="restaurant.invalid",
            cadence="hourly",
            section_keys=("measurement",),
            timezone="UTC",
            enabled=False,
            notification_channel="in_app",
            notification_enabled=True,
        )


def test_monitoring_feature_requires_console_feature() -> None:
    settings = Settings(
        restaurant_operations_console_enabled=False,
        restaurant_monitoring_enabled=True,
    )
    with pytest.raises(ValueError, match="requires"):
        settings.validate_restaurant_intelligence()


def test_operations_tables_register_additively() -> None:
    from catora_api.db.base import Base
    from catora_api.db.models.operations_console import (  # noqa: F401
        OperationsConsoleActionRecord,
        OperationsConsoleAlertRecord,
        OperationsConsoleExportRecord,
        OperationsConsoleSnapshotRecord,
        OperationsMonitorRunRecord,
        OperationsMonitorScheduleRecord,
    )

    assert {
        "operations_console_snapshots",
        "operations_console_alerts",
        "operations_console_actions",
        "operations_monitor_schedules",
        "operations_monitor_runs",
        "operations_console_exports",
    }.issubset(Base.metadata.tables)
