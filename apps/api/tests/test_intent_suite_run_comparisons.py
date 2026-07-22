from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.db.models.intents import IntentSuite, IntentSuiteRun
from catora_api.intents.suite_comparisons import (
    IntentSuiteRunComparisonConflictError,
    IntentSuiteRunComparisonService,
    _validated_summary,
)
from catora_api.intents.suites import (
    IntentSuiteRunSummary,
    PersistedIntentSuiteRun,
)


class FakeSuiteService:
    def __init__(self, runs: dict[uuid.UUID, PersistedIntentSuiteRun]) -> None:
        self.runs = runs
        self.calls: list[uuid.UUID] = []

    async def get_run(
        self,
        _session: object,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> PersistedIntentSuiteRun:
        del workspace_id
        self.calls.append(run_id)
        return self.runs[run_id]


def _summary(
    *,
    target_count: int,
    product_count: int,
    confident_match_count: int,
    possible_count: int,
    non_match_count: int,
    insufficient_count: int,
    coverage_basis_points: int,
) -> IntentSuiteRunSummary:
    return IntentSuiteRunSummary(
        member_count=2,
        intent_run_count=2,
        target_count=target_count,
        product_count=product_count,
        confident_match_count=confident_match_count,
        possible_match_missing_data_count=possible_count,
        non_match_count=non_match_count,
        insufficient_category_data_count=insufficient_count,
        confident_coverage_basis_points=coverage_basis_points,
    )


def _persisted(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    product_ids: tuple[uuid.UUID, ...],
    summary: IntentSuiteRunSummary,
) -> PersistedIntentSuiteRun:
    now = datetime.now(UTC)
    suite = IntentSuite(
        id=suite_id,
        workspace_id=workspace_id,
        name="Historical coverage",
        description=None,
        created_at=now,
        updated_at=now,
    )
    run = IntentSuiteRun(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        previous_run_id=None,
        status="completed",
        requested_product_ids=[str(item) for item in product_ids],
        source_snapshot_hash=uuid.uuid4().hex * 2,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    return PersistedIntentSuiteRun(
        run=run,
        suite=suite,
        child_runs=(),
        child_run_ids=(uuid.uuid4(), uuid.uuid4()),
        summary=summary,
        delta=None,
    )


@pytest.mark.asyncio
async def test_compare_returns_selected_minus_baseline_delta() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    baseline_products = (uuid.UUID(int=1),)
    run_products = (uuid.UUID(int=1), uuid.UUID(int=2))
    baseline = _persisted(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=baseline_products,
        summary=_summary(
            target_count=8,
            product_count=4,
            confident_match_count=4,
            possible_count=2,
            non_match_count=1,
            insufficient_count=1,
            coverage_basis_points=5000,
        ),
    )
    run = _persisted(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=run_products,
        summary=_summary(
            target_count=10,
            product_count=5,
            confident_match_count=6,
            possible_count=1,
            non_match_count=2,
            insufficient_count=1,
            coverage_basis_points=6000,
        ),
    )
    fake = FakeSuiteService({run.run.id: run, baseline.run.id: baseline})
    service = IntentSuiteRunComparisonService(cast(Any, fake))

    comparison = await service.compare(
        cast(Any, object()),
        workspace_id=workspace_id,
        run_id=run.run.id,
        baseline_run_id=baseline.run.id,
    )

    assert comparison.run.persisted is run
    assert comparison.baseline.persisted is baseline
    assert comparison.selection_changed is True
    assert comparison.delta.previous_run_id == baseline.run.id
    assert comparison.delta.target_count_delta == 2
    assert comparison.delta.confident_match_count_delta == 2
    assert comparison.delta.confident_coverage_basis_points_delta == 1000
    assert fake.calls == [run.run.id, baseline.run.id]


@pytest.mark.asyncio
async def test_compare_marks_equal_product_scopes() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    product_ids = (uuid.UUID(int=1),)
    summary = _summary(
        target_count=4,
        product_count=2,
        confident_match_count=2,
        possible_count=1,
        non_match_count=1,
        insufficient_count=0,
        coverage_basis_points=5000,
    )
    baseline = _persisted(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=product_ids,
        summary=summary,
    )
    run = _persisted(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=product_ids,
        summary=summary,
    )
    service = IntentSuiteRunComparisonService(
        cast(Any, FakeSuiteService({run.run.id: run, baseline.run.id: baseline}))
    )

    comparison = await service.compare(
        cast(Any, object()),
        workspace_id=workspace_id,
        run_id=run.run.id,
        baseline_run_id=baseline.run.id,
    )

    assert comparison.selection_changed is False
    assert comparison.delta.target_count_delta == 0


@pytest.mark.asyncio
async def test_compare_rejects_self_before_reading() -> None:
    run_id = uuid.uuid4()
    fake = FakeSuiteService({})
    service = IntentSuiteRunComparisonService(cast(Any, fake))

    with pytest.raises(IntentSuiteRunComparisonConflictError, match="itself"):
        await service.compare(
            cast(Any, object()),
            workspace_id=uuid.uuid4(),
            run_id=run_id,
            baseline_run_id=run_id,
        )

    assert fake.calls == []


@pytest.mark.asyncio
async def test_compare_rejects_cross_suite_runs() -> None:
    workspace_id = uuid.uuid4()
    summary = _summary(
        target_count=2,
        product_count=1,
        confident_match_count=1,
        possible_count=0,
        non_match_count=1,
        insufficient_count=0,
        coverage_basis_points=5000,
    )
    run = _persisted(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        product_ids=(),
        summary=summary,
    )
    baseline = _persisted(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        product_ids=(),
        summary=summary,
    )
    service = IntentSuiteRunComparisonService(
        cast(Any, FakeSuiteService({run.run.id: run, baseline.run.id: baseline}))
    )

    with pytest.raises(IntentSuiteRunComparisonConflictError, match="same suite"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            run_id=run.run.id,
            baseline_run_id=baseline.run.id,
        )


@pytest.mark.parametrize(
    "summary",
    [
        _summary(
            target_count=5,
            product_count=2,
            confident_match_count=2,
            possible_count=1,
            non_match_count=1,
            insufficient_count=0,
            coverage_basis_points=4000,
        ),
        IntentSuiteRunSummary(
            member_count=2,
            intent_run_count=1,
            target_count=4,
            product_count=2,
            confident_match_count=2,
            possible_match_missing_data_count=1,
            non_match_count=1,
            insufficient_category_data_count=0,
            confident_coverage_basis_points=5000,
        ),
        _summary(
            target_count=4,
            product_count=2,
            confident_match_count=2,
            possible_count=1,
            non_match_count=1,
            insufficient_count=0,
            coverage_basis_points=4999,
        ),
    ],
)
def test_summary_validation_fails_closed(summary: IntentSuiteRunSummary) -> None:
    with pytest.raises(IntentSuiteRunComparisonConflictError):
        _validated_summary(summary)


def test_comparison_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}/"
        "compare/{baseline_run_id}"
    )
    operation = app.openapi()["paths"][path]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/IntentSuiteRunComparisonView")
