from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from catora_api.auditing.append_only_service import AppendOnlyAuditRunService
from catora_api.db.models.audit import AuditFinding, AuditRun


class ScalarCollection:
    def __init__(self, values: list[AuditFinding]) -> None:
        self._values = values

    def all(self) -> list[AuditFinding]:
        return self._values


class RecordingSession:
    def __init__(self, results: list[list[AuditFinding]]) -> None:
        self._results = iter(results)
        self.added: list[AuditFinding] = []
        self.flushes = 0

    async def scalars(self, _statement: object) -> ScalarCollection:
        return ScalarCollection(next(self._results))

    def add(self, finding: AuditFinding) -> None:
        self.added.append(finding)

    async def flush(self) -> None:
        self.flushes += 1


def _run(*, previous_run_id: uuid.UUID | None) -> AuditRun:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    return AuditRun(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        previous_run_id=previous_run_id,
        taxonomy_version="1.0.0",
        mode="full",
        status="running",
        source_snapshot_hash=None,
        product_snapshot_hashes={},
        rule_version_set=[str(uuid.uuid4())],
        progress_current=0,
        progress_total=1,
        cancellation_requested=False,
        score_summary={},
        finding_counts={},
        failure_summary={},
        started_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def _finding(
    *,
    run: AuditRun,
    product_id: uuid.UUID,
    status: str,
) -> AuditFinding:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    return AuditFinding(
        id=uuid.uuid4(),
        workspace_id=run.workspace_id,
        audit_run_id=run.id,
        previous_finding_id=None,
        rule_version_id=uuid.uuid4(),
        product_id=product_id,
        variant_id=None,
        severity="high",
        title="Width missing",
        explanation="Width is required",
        fingerprint="a" * 64,
        status=status,
        field_key="width_mm",
        affected_value=None,
        business_impact="data_quality",
        remediation_type="supply_source_value",
        failure_codes=["missing_value"],
        evidence=[],
        first_seen_at=now,
        last_seen_at=now,
        resolved_at=now if status == "resolved" else None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_full_run_resolution_is_appended_without_mutating_previous_run() -> None:
    previous_run = _run(previous_run_id=None)
    previous_run.status = "completed"
    previous = _finding(
        run=previous_run,
        product_id=uuid.uuid4(),
        status="ongoing",
    )
    run = _run(previous_run_id=previous_run.id)
    run.workspace_id = previous_run.workspace_id
    session = RecordingSession([[previous]])

    statuses, resolved_count = await AppendOnlyAuditRunService()._reconcile_findings(
        session,  # type: ignore[arg-type]
        run=run,
        findings={},
    )

    assert statuses == []
    assert resolved_count == 1
    assert previous.status == "ongoing"
    assert previous.resolved_at is None
    assert len(session.added) == 1
    resolved = session.added[0]
    assert resolved.audit_run_id == run.id
    assert resolved.previous_finding_id == previous.id
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None


@pytest.mark.asyncio
async def test_incremental_run_carries_unchanged_finding_forward() -> None:
    previous_run = _run(previous_run_id=None)
    previous_run.status = "completed"
    product_id = uuid.uuid4()
    previous = _finding(run=previous_run, product_id=product_id, status="new")
    run = _run(previous_run_id=previous_run.id)
    run.workspace_id = previous_run.workspace_id
    run.mode = "incremental"
    session = RecordingSession([[previous]])

    statuses, resolved_count = (
        await AppendOnlyAuditRunService()._reconcile_incremental_findings(
            session,  # type: ignore[arg-type]
            run=run,
            findings={},
            target_product_ids=set(),
        )
    )

    assert statuses == ["ongoing"]
    assert resolved_count == 0
    assert previous.status == "new"
    assert len(session.added) == 1
    carried = session.added[0]
    assert carried.audit_run_id == run.id
    assert carried.previous_finding_id == previous.id
    assert carried.product_id == product_id
    assert carried.status == "ongoing"
    assert carried.resolved_at is None


@pytest.mark.asyncio
async def test_resolved_transition_is_not_carried_indefinitely() -> None:
    previous_run = _run(previous_run_id=None)
    previous_run.status = "completed"
    previous = _finding(
        run=previous_run,
        product_id=uuid.uuid4(),
        status="resolved",
    )
    run = _run(previous_run_id=previous_run.id)
    run.workspace_id = previous_run.workspace_id
    run.mode = "incremental"
    session = RecordingSession([[previous]])

    statuses, resolved_count = (
        await AppendOnlyAuditRunService()._reconcile_incremental_findings(
            session,  # type: ignore[arg-type]
            run=run,
            findings={},
            target_product_ids=set(),
        )
    )

    assert statuses == []
    assert resolved_count == 0
    assert session.added == []
