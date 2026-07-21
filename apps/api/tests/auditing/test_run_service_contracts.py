from __future__ import annotations

import uuid

import pytest

from catora_api.auditing.service import AuditRunService
from catora_api.db.models.audit import AuditRun


class CancellationSession:
    def __init__(self, run: AuditRun) -> None:
        self.run = run
        self.flushes = 0

    async def scalar(self, _statement: object) -> AuditRun:
        return self.run

    async def flush(self) -> None:
        self.flushes += 1


def _run(*, status: str) -> AuditRun:
    return AuditRun(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        taxonomy_version="1.0.0",
        mode="full",
        status=status,
        source_snapshot_hash=None,
        rule_version_set=[str(uuid.uuid4())],
        progress_current=0,
        progress_total=0,
        cancellation_requested=False,
        score_summary={},
        finding_counts={},
        failure_summary={},
    )


@pytest.mark.asyncio
async def test_queued_run_cancellation_is_immediate() -> None:
    run = _run(status="queued")
    session = CancellationSession(run)

    result = await AuditRunService().request_cancellation(
        session,  # type: ignore[arg-type]
        workspace_id=run.workspace_id,
        run_id=run.id,
    )

    assert result.status == "cancelled"
    assert result.cancellation_requested is True
    assert result.completed_at is not None
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_running_run_cancellation_remains_cooperative() -> None:
    run = _run(status="running")
    session = CancellationSession(run)

    result = await AuditRunService().request_cancellation(
        session,  # type: ignore[arg-type]
        workspace_id=run.workspace_id,
        run_id=run.id,
    )

    assert result.status == "running"
    assert result.cancellation_requested is True
    assert result.completed_at is None
    assert session.flushes == 1


def test_active_run_uniqueness_is_declared_in_the_orm_contract() -> None:
    index = next(
        item
        for item in AuditRun.__table__.indexes
        if item.name == "uq_audit_runs_active_workspace"
    )

    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None
