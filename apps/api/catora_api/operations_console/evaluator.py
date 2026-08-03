from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from catora_api.operations_console.models import (
    AlertSeverity,
    ConsoleActionProposal,
    ConsoleAlert,
    ConsoleSection,
    ConsoleSectionKey,
    ExportFormat,
    OperationsExportBundle,
    RestaurantConsoleSnapshot,
)

_CRITICAL_SECTION_KEYS: frozenset[ConsoleSectionKey] = frozenset(
    {"catalog_freshness", "technical_seo", "local_profiles"}
)
_FORBIDDEN_EXPORT_TERMS = (
    "authorization",
    "cookie",
    "credential_reference",
    "password",
    "private_key",
    "secret",
    "session_id",
    "access_token",
    "refresh_token",
)
TargetWorkflow = Literal[
    "change_set",
    "git_proposal",
    "local_profile_review",
    "review_response_draft",
    "authority_outreach_draft",
    "provider_connection",
    "manual_review",
]


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def compose_console_snapshot(
    *,
    workspace_id: UUID,
    sections: tuple[ConsoleSection, ...],
    generated_at: datetime | None = None,
    brand_id: UUID | None = None,
    location_id: UUID | None = None,
) -> RestaurantConsoleSnapshot:
    instant = generated_at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    ordered = tuple(sorted(sections, key=lambda section: section.key))
    normalized = tuple(_apply_freshness(section, instant) for section in ordered)
    alerts = derive_console_alerts(normalized, detected_at=instant)
    payload = {
        "version": "restaurant-operations-console/v1",
        "workspace_id": str(workspace_id),
        "brand_id": str(brand_id) if brand_id else None,
        "location_id": str(location_id) if location_id else None,
        "generated_at": instant.isoformat(),
        "sections": [section.model_dump(mode="json") for section in normalized],
    }
    return RestaurantConsoleSnapshot(
        workspace_id=workspace_id,
        brand_id=brand_id,
        location_id=location_id,
        generated_at=instant,
        sections=normalized,
        available_section_count=sum(
            section.state in {"current", "partial"} for section in normalized
        ),
        stale_section_count=sum(section.state == "stale" for section in normalized),
        unavailable_section_count=sum(
            section.state in {"unavailable", "disconnected", "blocked"}
            for section in normalized
        ),
        critical_alert_count=sum(alert.severity == "critical" for alert in alerts),
        snapshot_sha256=canonical_hash(payload),
    )


def derive_console_alerts(
    sections: tuple[ConsoleSection, ...],
    *,
    detected_at: datetime,
) -> tuple[ConsoleAlert, ...]:
    if detected_at.tzinfo is None:
        raise ValueError("detected_at must be timezone-aware")
    alerts: list[ConsoleAlert] = []
    for section in sections:
        if section.state == "current":
            continue
        severity, detail = _alert_detail(section)
        evidence = section.evidence_references or (f"section:{section.key}",)
        fingerprint = canonical_hash(
            {
                "section": section.key,
                "state": section.state,
                "detail": detail,
                "evidence": evidence,
            }
        )
        alerts.append(
            ConsoleAlert(
                alert_key=f"console.{section.key}.{section.state}",
                severity=severity,
                title=f"{section.title}: {section.state.replace('_', ' ')}",
                detail=detail,
                section_key=section.key,
                evidence_references=evidence,
                detected_at=detected_at,
                fingerprint=fingerprint,
            )
        )
    severity_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "informational": 4,
    }
    return tuple(
        sorted(alerts, key=lambda alert: (severity_order[alert.severity], alert.alert_key))
    )


def propose_console_actions(
    alerts: tuple[ConsoleAlert, ...],
) -> tuple[ConsoleActionProposal, ...]:
    actions: list[ConsoleActionProposal] = []
    for alert in alerts:
        workflow, owner, verification = _workflow_for_section(alert.section_key)
        actions.append(
            ConsoleActionProposal(
                action_key=f"action:{alert.fingerprint}",
                section_key=alert.section_key,
                title=f"Review {alert.title}",
                rationale=alert.detail,
                owner_role=owner,
                verification_method=verification,
                evidence_references=alert.evidence_references,
                target_workflow=workflow,
            )
        )
    return tuple(actions)


def render_operations_export(
    snapshot: RestaurantConsoleSnapshot,
    *,
    snapshot_id: UUID,
    export_format: ExportFormat,
    generated_at: datetime | None = None,
) -> OperationsExportBundle:
    instant = generated_at or datetime.now(UTC)
    if export_format == "json":
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        content_type = "application/json"
    else:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "section_key",
                "section_state",
                "metric_key",
                "metric_label",
                "metric_value",
                "unit",
                "definition_version",
                "source_coverage",
                "window_start",
                "window_end",
                "observed_at",
            ]
        )
        for section in snapshot.sections:
            if not section.metrics:
                writer.writerow(
                    [
                        section.key,
                        section.state,
                        "",
                        section.title,
                        "",
                        "",
                        "restaurant-operations-console/v1",
                        section.summary,
                        "",
                        "",
                        section.observed_at.isoformat() if section.observed_at else "",
                    ]
                )
                continue
            for metric in section.metrics:
                writer.writerow(
                    [
                        section.key,
                        section.state,
                        metric.key,
                        metric.label,
                        "" if metric.value is None else str(metric.value),
                        metric.unit or "",
                        metric.definition_version,
                        metric.source_coverage,
                        metric.window_start.isoformat() if metric.window_start else "",
                        metric.window_end.isoformat() if metric.window_end else "",
                        metric.observed_at.isoformat() if metric.observed_at else "",
                    ]
                )
        payload = buffer.getvalue()
        content_type = "text/csv; charset=utf-8"
    _assert_sanitized(payload)
    payload_bytes = payload.encode("utf-8")
    if len(payload_bytes) > 5 * 1024 * 1024:
        raise ValueError("Operations export exceeds the 5 MiB safety limit")
    return OperationsExportBundle(
        snapshot_id=snapshot_id,
        export_format=export_format,
        content_type=content_type,
        payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        byte_size=len(payload_bytes),
        generated_at=instant,
        sanitized_payload=payload,
    )


def _apply_freshness(section: ConsoleSection, instant: datetime) -> ConsoleSection:
    if (
        section.state in {"current", "partial"}
        and section.stale_after is not None
        and section.stale_after <= instant
    ):
        return section.model_copy(
            update={
                "state": "stale",
                "summary": f"{section.summary} Evidence is now stale.",
            }
        )
    return section


def _alert_detail(section: ConsoleSection) -> tuple[AlertSeverity, str]:
    critical = section.key in _CRITICAL_SECTION_KEYS
    if section.state == "partial":
        return "medium", f"{section.title} has incomplete evidence or coverage."
    if section.state == "stale":
        return (
            "high" if critical else "medium",
            f"{section.title} is older than its approved freshness policy.",
        )
    if section.state == "blocked":
        return (
            "critical" if critical else "high",
            section.unavailable_reason or f"{section.title} is blocked.",
        )
    return (
        "high" if critical else "low",
        section.unavailable_reason or f"{section.title} is unavailable.",
    )


def _workflow_for_section(
    section_key: ConsoleSectionKey,
) -> tuple[TargetWorkflow, str, str]:
    if section_key in {"technical_seo", "catalog_freshness", "answer_readiness"}:
        return (
            "git_proposal",
            "seo_owner",
            "Run an approved recheck after the reviewed pull request is merged externally.",
        )
    if section_key == "local_profiles":
        return (
            "local_profile_review",
            "local_visibility_owner",
            "Re-observe the approved profile after the human provider action.",
        )
    if section_key == "reputation":
        return (
            "review_response_draft",
            "reputation_owner",
            "Record the human reviewer decision and public response separately.",
        )
    if section_key == "authority":
        return (
            "authority_outreach_draft",
            "pr_owner",
            "Record the reviewer decision and independently published outcome.",
        )
    if section_key == "measurement":
        return (
            "provider_connection",
            "analytics_owner",
            "Verify provider capability, property access and a current aggregate observation.",
        )
    return (
        "manual_review",
        "workspace_owner",
        "Record the human decision and attach updated evidence.",
    )


def _assert_sanitized(payload: str) -> None:
    normalized = payload.casefold()
    present = [term for term in _FORBIDDEN_EXPORT_TERMS if term in normalized]
    if present:
        raise ValueError(f"Operations export contains restricted fields: {sorted(present)}")
