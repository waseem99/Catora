from __future__ import annotations

import calendar
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.operations_console import (
    OperationsConsoleActionRecord,
    OperationsConsoleAlertRecord,
    OperationsConsoleExportRecord,
    OperationsConsoleSnapshotRecord,
    OperationsMonitorRunRecord,
    OperationsMonitorScheduleRecord,
)
from catora_api.operations_console.evaluator import (
    compose_console_snapshot,
    derive_console_alerts,
    propose_console_actions,
    render_operations_export,
)
from catora_api.operations_console.models import (
    ExportFormat,
    MonitorSchedule,
    OperationsExportBundle,
    RestaurantConsoleSnapshot,
)
from catora_api.operations_console.reconciler import reconcile_persisted_sections


class OperationsConsoleServiceError(ValueError):
    pass


class OperationsConsoleService:
    async def generate(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        brand_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        generated_at: datetime | None = None,
    ) -> OperationsConsoleSnapshotRecord:
        instant = generated_at or datetime.now(UTC)
        sections = await reconcile_persisted_sections(
            session,
            workspace_id=workspace_id,
            generated_at=instant,
            brand_id=brand_id,
            location_id=location_id,
        )
        snapshot = compose_console_snapshot(
            workspace_id=workspace_id,
            sections=sections,
            generated_at=instant,
            brand_id=brand_id,
            location_id=location_id,
        )
        row = await self._persist_snapshot(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            snapshot=snapshot,
        )
        await session.commit()
        return row

    async def _persist_snapshot(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        snapshot: RestaurantConsoleSnapshot,
    ) -> OperationsConsoleSnapshotRecord:
        existing = await session.scalar(
            select(OperationsConsoleSnapshotRecord).where(
                OperationsConsoleSnapshotRecord.workspace_id == workspace_id,
                OperationsConsoleSnapshotRecord.snapshot_sha256
                == snapshot.snapshot_sha256,
            )
        )
        if existing is not None:
            return existing
        row = OperationsConsoleSnapshotRecord(
            workspace_id=workspace_id,
            brand_id=snapshot.brand_id,
            location_id=snapshot.location_id,
            definition_version=snapshot.version,
            generated_at=snapshot.generated_at,
            snapshot_sha256=snapshot.snapshot_sha256,
            snapshot=snapshot.model_dump(mode="json"),
            section_states={section.key: section.state for section in snapshot.sections},
        )
        session.add(row)
        await session.flush()
        alerts = derive_console_alerts(
            snapshot.sections,
            detected_at=snapshot.generated_at,
        )
        current_fingerprints = {alert.fingerprint for alert in alerts}
        await self._resolve_absent_alerts(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            current_fingerprints=current_fingerprints,
            resolved_at=snapshot.generated_at,
        )
        alert_rows: dict[str, OperationsConsoleAlertRecord] = {}
        for alert in alerts:
            alert_row = await session.scalar(
                select(OperationsConsoleAlertRecord).where(
                    OperationsConsoleAlertRecord.workspace_id == workspace_id,
                    OperationsConsoleAlertRecord.fingerprint == alert.fingerprint,
                )
            )
            if alert_row is None:
                alert_row = OperationsConsoleAlertRecord(
                    workspace_id=workspace_id,
                    snapshot_id=row.id,
                    alert_key=alert.alert_key,
                    section_key=alert.section_key,
                    severity=alert.severity,
                    status="open",
                    title=alert.title,
                    detail=alert.detail,
                    evidence_references=list(alert.evidence_references),
                    detected_at=alert.detected_at,
                    fingerprint=alert.fingerprint,
                )
                session.add(alert_row)
                await session.flush()
            alert_rows[alert.fingerprint] = alert_row
        for action in propose_console_actions(alerts):
            existing_action = await session.scalar(
                select(OperationsConsoleActionRecord).where(
                    OperationsConsoleActionRecord.workspace_id == workspace_id,
                    OperationsConsoleActionRecord.action_key == action.action_key,
                )
            )
            if existing_action is not None:
                continue
            alert_fingerprint = action.action_key.removeprefix("action:")
            alert_row = alert_rows.get(alert_fingerprint)
            session.add(
                OperationsConsoleActionRecord(
                    workspace_id=workspace_id,
                    alert_id=alert_row.id if alert_row else None,
                    action_key=action.action_key,
                    section_key=action.section_key,
                    title=action.title,
                    rationale=action.rationale,
                    owner_role=action.owner_role,
                    verification_method=action.verification_method,
                    evidence_references=list(action.evidence_references),
                    target_workflow=action.target_workflow,
                    state=action.state,
                    direct_mutation_allowed=False,
                )
            )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="operations_console.snapshot_generated",
                entity_type="operations_console_snapshot",
                entity_id=row.id,
                payload={
                    "snapshot_sha256": snapshot.snapshot_sha256,
                    "available_sections": snapshot.available_section_count,
                    "stale_sections": snapshot.stale_section_count,
                    "unavailable_sections": snapshot.unavailable_section_count,
                    "alert_count": len(alerts),
                    "causal_claim_allowed": False,
                    "direct_mutation_allowed": False,
                },
            )
        )
        return row

    async def create_export(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        export_format: ExportFormat,
    ) -> OperationsConsoleExportRecord:
        snapshot_row = await session.scalar(
            select(OperationsConsoleSnapshotRecord).where(
                OperationsConsoleSnapshotRecord.workspace_id == workspace_id,
                OperationsConsoleSnapshotRecord.id == snapshot_id,
            )
        )
        if snapshot_row is None:
            raise OperationsConsoleServiceError("Operations console snapshot not found")
        snapshot = RestaurantConsoleSnapshot.model_validate(snapshot_row.snapshot)
        bundle = render_operations_export(
            snapshot,
            snapshot_id=snapshot_row.id,
            export_format=export_format,
        )
        existing = await session.scalar(
            select(OperationsConsoleExportRecord).where(
                OperationsConsoleExportRecord.workspace_id == workspace_id,
                OperationsConsoleExportRecord.snapshot_id == snapshot_id,
                OperationsConsoleExportRecord.export_format == export_format,
                OperationsConsoleExportRecord.payload_sha256 == bundle.payload_sha256,
            )
        )
        if existing is not None:
            return existing
        row = OperationsConsoleExportRecord(
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            export_format=export_format,
            content_type=bundle.content_type,
            schema_version=bundle.schema_version,
            payload_sha256=bundle.payload_sha256,
            byte_size=bundle.byte_size,
            sanitized_payload=bundle.sanitized_payload,
            created_by_user_id=actor_user_id,
            generated_at=bundle.generated_at,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="operations_console.export_generated",
                entity_type="operations_console_export",
                entity_id=row.id,
                payload={
                    "snapshot_id": str(snapshot_id),
                    "format": export_format,
                    "payload_sha256": bundle.payload_sha256,
                    "byte_size": bundle.byte_size,
                    "contains_secrets": False,
                    "contains_personal_data": False,
                },
            )
        )
        await session.commit()
        return row

    async def acknowledge_alert(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        alert_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> OperationsConsoleAlertRecord:
        row = await self._alert(session, workspace_id=workspace_id, alert_id=alert_id)
        if row.status == "resolved":
            raise OperationsConsoleServiceError("Resolved alerts cannot be acknowledged")
        row.status = "acknowledged"
        row.acknowledged_by_user_id = actor_user_id
        row.acknowledged_at = datetime.now(UTC)
        await session.commit()
        return row

    async def resolve_alert(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        alert_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        note: str,
    ) -> OperationsConsoleAlertRecord:
        row = await self._alert(session, workspace_id=workspace_id, alert_id=alert_id)
        row.status = "resolved"
        row.resolved_by_user_id = actor_user_id
        row.resolved_at = datetime.now(UTC)
        row.resolution_note = note
        await session.commit()
        return row

    async def decide_action(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        action_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        decision: str,
        reason: str,
    ) -> OperationsConsoleActionRecord:
        if decision not in {"approved", "rejected", "completed", "blocked"}:
            raise OperationsConsoleServiceError("Unsupported action decision")
        row = await session.scalar(
            select(OperationsConsoleActionRecord).where(
                OperationsConsoleActionRecord.id == action_id,
                OperationsConsoleActionRecord.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise OperationsConsoleServiceError("Console action not found")
        if row.direct_mutation_allowed:
            raise OperationsConsoleServiceError("Console actions cannot permit direct mutation")
        row.state = decision
        row.decided_by_user_id = actor_user_id
        row.decided_at = datetime.now(UTC)
        row.decision_reason = reason
        await session.commit()
        return row

    async def upsert_schedule(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        schedule: MonitorSchedule,
    ) -> OperationsMonitorScheduleRecord:
        row = await session.scalar(
            select(OperationsMonitorScheduleRecord).where(
                OperationsMonitorScheduleRecord.workspace_id == workspace_id,
                OperationsMonitorScheduleRecord.schedule_key == schedule.schedule_key,
            )
        )
        if row is None:
            row = OperationsMonitorScheduleRecord(
                workspace_id=workspace_id,
                schedule_key=schedule.schedule_key,
                cadence=schedule.cadence,
                section_keys=list(schedule.section_keys),
                timezone=schedule.timezone,
                enabled=schedule.enabled,
                next_due_at=schedule.next_due_at,
                notification_channel=schedule.notification_channel,
                notification_enabled=schedule.notification_enabled,
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
            session.add(row)
        else:
            row.cadence = schedule.cadence
            row.section_keys = list(schedule.section_keys)
            row.timezone = schedule.timezone
            row.enabled = schedule.enabled
            row.next_due_at = schedule.next_due_at
            row.notification_channel = schedule.notification_channel
            row.notification_enabled = schedule.notification_enabled
            row.updated_by_user_id = actor_user_id
        await session.commit()
        return row

    async def run_schedule(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        schedule_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        now: datetime | None = None,
    ) -> OperationsMonitorRunRecord:
        instant = now or datetime.now(UTC)
        schedule = await session.scalar(
            select(OperationsMonitorScheduleRecord)
            .where(
                OperationsMonitorScheduleRecord.workspace_id == workspace_id,
                OperationsMonitorScheduleRecord.id == schedule_id,
            )
            .with_for_update()
        )
        if schedule is None:
            raise OperationsConsoleServiceError("Monitor schedule not found")
        if not schedule.enabled:
            raise OperationsConsoleServiceError("Monitor schedule is disabled")
        due = schedule.next_due_at or instant
        idempotency_key = f"{schedule.id}:{due.isoformat()}"
        existing = await session.scalar(
            select(OperationsMonitorRunRecord).where(
                OperationsMonitorRunRecord.workspace_id == workspace_id,
                OperationsMonitorRunRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        run = OperationsMonitorRunRecord(
            workspace_id=workspace_id,
            schedule_id=schedule.id,
            idempotency_key=idempotency_key,
            status="running",
            started_at=instant,
            summary={},
            failure_detail={},
        )
        session.add(run)
        await session.flush()
        sections = await reconcile_persisted_sections(
            session,
            workspace_id=workspace_id,
            generated_at=instant,
        )
        selected = tuple(section for section in sections if section.key in schedule.section_keys)
        snapshot = compose_console_snapshot(
            workspace_id=workspace_id,
            sections=selected,
            generated_at=instant,
        )
        snapshot_row = await self._persist_snapshot(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            snapshot=snapshot,
        )
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.snapshot_id = snapshot_row.id
        run.summary = {
            "snapshot_sha256": snapshot.snapshot_sha256,
            "available_sections": snapshot.available_section_count,
            "stale_sections": snapshot.stale_section_count,
            "unavailable_sections": snapshot.unavailable_section_count,
            "notification_recorded_only": schedule.notification_enabled,
            "notification_sent": False,
        }
        schedule.next_due_at = _next_due(
            due,
            cadence=schedule.cadence,
            timezone=schedule.timezone,
        )
        await session.commit()
        return run

    async def _resolve_absent_alerts(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        current_fingerprints: set[str],
        resolved_at: datetime,
    ) -> None:
        rows = (
            await session.scalars(
                select(OperationsConsoleAlertRecord).where(
                    OperationsConsoleAlertRecord.workspace_id == workspace_id,
                    OperationsConsoleAlertRecord.status.in_(("open", "acknowledged")),
                )
            )
        ).all()
        for row in rows:
            if row.fingerprint in current_fingerprints:
                continue
            row.status = "resolved"
            row.resolved_by_user_id = actor_user_id
            row.resolved_at = resolved_at
            row.resolution_note = "The evidence state was absent from the next persisted snapshot."

    async def _alert(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        alert_id: uuid.UUID,
    ) -> OperationsConsoleAlertRecord:
        row = await session.scalar(
            select(OperationsConsoleAlertRecord).where(
                OperationsConsoleAlertRecord.id == alert_id,
                OperationsConsoleAlertRecord.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise OperationsConsoleServiceError("Console alert not found")
        return row


def export_bundle_from_record(row: OperationsConsoleExportRecord) -> OperationsExportBundle:
    return OperationsExportBundle(
        snapshot_id=row.snapshot_id,
        export_format=row.export_format,
        content_type=row.content_type,
        payload_sha256=row.payload_sha256,
        byte_size=row.byte_size,
        generated_at=row.generated_at,
        sanitized_payload=row.sanitized_payload,
    )


def _next_due(value: datetime, *, cadence: str, timezone: str) -> datetime:
    local = value.astimezone(ZoneInfo(timezone))
    if cadence == "hourly":
        result = local + timedelta(hours=1)
    elif cadence == "daily":
        result = local + timedelta(days=1)
    elif cadence == "weekly":
        result = local + timedelta(weeks=1)
    elif cadence == "monthly":
        year = local.year + (1 if local.month == 12 else 0)
        month = 1 if local.month == 12 else local.month + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        result = local.replace(year=year, month=month, day=day)
    else:
        raise OperationsConsoleServiceError("Unsupported monitor cadence")
    return result.astimezone(UTC)
