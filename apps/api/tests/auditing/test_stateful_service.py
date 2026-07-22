from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from catora_api.auditing.service import AuditConfigurationError
from catora_api.auditing.stateful_service import StatefulAuditRunService
from catora_api.db.models.audit import AuditRun


class ScalarCollection:
    def __init__(self, values: list[uuid.UUID | None]) -> None:
        self._values = values

    def all(self) -> list[uuid.UUID | None]:
        return self._values


class BaselineSession:
    def __init__(
        self,
        scalar_values: list[object | None],
        *,
        rule_version_ids: list[uuid.UUID] | None = None,
    ) -> None:
        self._scalar_values = iter(scalar_values)
        self._rule_version_ids = rule_version_ids or [uuid.uuid4()]

    async def scalar(self, _statement: object) -> object | None:
        return next(self._scalar_values)

    async def scalars(self, _statement: object) -> ScalarCollection:
        return ScalarCollection(list(self._rule_version_ids))


class ChangeSession:
    def __init__(self, results: list[list[uuid.UUID | None]]) -> None:
        self._results = iter(results)

    async def scalars(self, _statement: object) -> ScalarCollection:
        return ScalarCollection(next(self._results))


def _previous_run(*, hashes: dict[str, str]) -> AuditRun:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    return AuditRun(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        previous_run_id=None,
        taxonomy_version="1.0.0",
        mode="full",
        status="completed",
        source_snapshot_hash="a" * 64,
        product_snapshot_hashes=hashes,
        rule_version_set=[str(uuid.uuid4())],
        progress_current=1,
        progress_total=1,
        cancellation_requested=False,
        score_summary={
            "formula_version": "weighted-health-v1",
            "overall": {"contributions": []},
        },
        finding_counts={},
        failure_summary={},
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_incremental_run_requires_a_completed_baseline() -> None:
    session = BaselineSession([None, None])

    with pytest.raises(AuditConfigurationError, match="completed.*baseline"):
        await StatefulAuditRunService().create_run(
            session,  # type: ignore[arg-type]
            workspace_id=uuid.uuid4(),
            requested_by_user_id=uuid.uuid4(),
            taxonomy_version="1.0.0",
            mode="incremental",
        )


@pytest.mark.asyncio
async def test_incremental_run_rejects_rule_version_drift() -> None:
    previous = _previous_run(hashes={str(uuid.uuid4()): "a" * 64})
    session = BaselineSession(
        [None, previous],
        rule_version_ids=[uuid.uuid4()],
    )

    with pytest.raises(AuditConfigurationError, match="rule-version set"):
        await StatefulAuditRunService().create_run(
            session,  # type: ignore[arg-type]
            workspace_id=previous.workspace_id,
            requested_by_user_id=uuid.uuid4(),
            taxonomy_version="1.0.0",
            mode="incremental",
        )


@pytest.mark.asyncio
async def test_change_selection_includes_updates_and_removed_products() -> None:
    removed = uuid.uuid4()
    current = uuid.uuid4()
    product_change = uuid.uuid4()
    variant_change = uuid.uuid4()
    attribute_change = uuid.uuid4()
    direct_evidence_change = uuid.uuid4()
    attribute_evidence_change = uuid.uuid4()
    previous = _previous_run(
        hashes={str(removed): "a" * 64, str(current): "b" * 64}
    )
    session = ChangeSession(
        [
            [product_change],
            [variant_change],
            [attribute_change],
            [direct_evidence_change, None],
            [attribute_evidence_change],
        ]
    )
    run = AuditRun(
        id=uuid.uuid4(),
        workspace_id=previous.workspace_id,
        requested_by_user_id=uuid.uuid4(),
        previous_run_id=previous.id,
        taxonomy_version="1.0.0",
        mode="incremental",
        status="queued",
        source_snapshot_hash=None,
        product_snapshot_hashes={},
        rule_version_set=[str(uuid.uuid4())],
        progress_current=0,
        progress_total=0,
        cancellation_requested=False,
        score_summary={},
        finding_counts={},
        failure_summary={},
    )

    changed = await StatefulAuditRunService()._changed_product_ids(
        session,  # type: ignore[arg-type]
        run=run,
        previous=previous,
        current_product_ids={current},
    )

    assert changed == {
        removed,
        product_change,
        variant_change,
        attribute_change,
        direct_evidence_change,
        attribute_evidence_change,
    }
