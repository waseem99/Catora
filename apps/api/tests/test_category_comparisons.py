from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.db.models.intents import IntentSuiteRun
from catora_api.intents.category_comparisons import (
    IntentCategoryCoverageComparisonService,
    build_category_comparison,
)
from catora_api.intents.coverage import (
    IntentCategoryCoverage,
    IntentCategoryCoverageReport,
    IntentCoverageDataError,
    IntentCoverageTotals,
)
from catora_api.intents.suites import coverage_basis_points


def _suite_run(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    label: str,
    product_ids: list[str],
) -> IntentSuiteRun:
    now = datetime.now(UTC)
    return IntentSuiteRun(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"category-comparison:{label}"),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        previous_run_id=None,
        status="completed",
        requested_product_ids=product_ids,
        source_snapshot_hash=("a" if label == "selected" else "b") * 64,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


def _category(
    category_key: str | None,
    *,
    intent_count: int,
    product_count: int,
    confident: int = 0,
    possible: int = 0,
    non_match: int = 0,
    insufficient: int = 0,
) -> IntentCategoryCoverage:
    target_count = confident + possible + non_match + insufficient
    return IntentCategoryCoverage(
        category_key=category_key,
        intent_count=intent_count,
        target_count=target_count,
        product_count=product_count,
        confident_match_count=confident,
        possible_match_missing_data_count=possible,
        non_match_count=non_match,
        insufficient_category_data_count=insufficient,
        confident_coverage_basis_points=coverage_basis_points(
            confident,
            target_count,
        ),
    )


def _totals(
    *,
    intent_count: int,
    product_count: int,
    confident: int = 0,
    possible: int = 0,
    non_match: int = 0,
    insufficient: int = 0,
) -> IntentCoverageTotals:
    target_count = confident + possible + non_match + insufficient
    return IntentCoverageTotals(
        intent_count=intent_count,
        target_count=target_count,
        product_count=product_count,
        confident_match_count=confident,
        possible_match_missing_data_count=possible,
        non_match_count=non_match,
        insufficient_category_data_count=insufficient,
        confident_coverage_basis_points=coverage_basis_points(
            confident,
            target_count,
        ),
    )


def _reports(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
) -> tuple[IntentCategoryCoverageReport, IntentCategoryCoverageReport]:
    first_product = str(uuid.UUID(int=1))
    second_product = str(uuid.UUID(int=2))
    selected = IntentCategoryCoverageReport(
        run=_suite_run(
            workspace_id=workspace_id,
            suite_id=suite_id,
            label="selected",
            product_ids=[first_product, second_product],
        ),
        items=(
            _category("chairs", intent_count=1, product_count=1, confident=1),
            _category(
                "sofas",
                intent_count=2,
                product_count=2,
                confident=1,
                non_match=1,
            ),
            _category(
                None,
                intent_count=1,
                product_count=1,
                insufficient=1,
            ),
        ),
        totals=_totals(
            intent_count=2,
            product_count=3,
            confident=2,
            non_match=1,
            insufficient=1,
        ),
    )
    baseline = IntentCategoryCoverageReport(
        run=_suite_run(
            workspace_id=workspace_id,
            suite_id=suite_id,
            label="baseline",
            product_ids=[first_product],
        ),
        items=(
            _category("beds", intent_count=1, product_count=1, non_match=1),
            _category("sofas", intent_count=1, product_count=1, confident=1),
            _category(
                None,
                intent_count=1,
                product_count=1,
                insufficient=1,
            ),
        ),
        totals=_totals(
            intent_count=2,
            product_count=2,
            confident=1,
            non_match=1,
            insufficient=1,
        ),
    )
    return selected, baseline


def test_category_union_order_presence_and_zero_filled_deltas() -> None:
    selected, baseline = _reports(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
    )

    items = build_category_comparison(selected, baseline)

    assert [item.category_key for item in items] == [
        "beds",
        "chairs",
        "sofas",
        None,
    ]
    assert [item.presence for item in items] == [
        "removed",
        "added",
        "retained",
        "retained",
    ]
    removed, added, retained, unclassified = items
    assert removed.selected is None
    assert removed.baseline is not None
    assert removed.delta.target_count_delta == -1
    assert removed.delta.non_match_count_delta == -1
    assert added.selected is not None
    assert added.baseline is None
    assert added.delta.confident_match_count_delta == 1
    assert added.delta.confident_coverage_basis_points_delta == 10_000
    assert retained.delta.target_count_delta == 1
    assert retained.delta.confident_match_count_delta == 0
    assert retained.delta.non_match_count_delta == 1
    assert retained.delta.confident_coverage_basis_points_delta == -5_000
    assert unclassified.delta.target_count_delta == 0


class FakeCoverageService:
    def __init__(
        self,
        selected: IntentCategoryCoverageReport,
        baseline: IntentCategoryCoverageReport,
    ) -> None:
        self.selected = selected
        self.baseline = baseline
        self.calls: list[uuid.UUID] = []

    async def category_coverage(
        self,
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentCategoryCoverageReport:
        assert workspace_id == self.selected.run.workspace_id
        self.calls.append(suite_run_id)
        if suite_run_id == self.selected.run.id:
            return self.selected
        return self.baseline


@pytest.mark.asyncio
async def test_service_reports_scope_change_and_suite_totals_delta() -> None:
    workspace_id = uuid.uuid4()
    selected, baseline = _reports(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
    )
    fake = FakeCoverageService(selected, baseline)
    service = IntentCategoryCoverageComparisonService(cast(Any, fake))

    report = await service.compare(
        cast(Any, object()),
        workspace_id=workspace_id,
        selected_suite_run_id=selected.run.id,
        baseline_suite_run_id=baseline.run.id,
    )

    assert fake.calls == [selected.run.id, baseline.run.id]
    assert report.selection_changed is True
    assert report.totals_delta.target_count_delta == 1
    assert report.totals_delta.product_count_delta == 1
    assert report.totals_delta.confident_match_count_delta == 1
    assert report.totals_delta.confident_coverage_basis_points_delta == 1_667


@pytest.mark.asyncio
async def test_self_and_cross_suite_comparisons_fail_closed() -> None:
    workspace_id = uuid.uuid4()
    selected, baseline = _reports(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
    )
    fake = FakeCoverageService(selected, baseline)
    service = IntentCategoryCoverageComparisonService(cast(Any, fake))

    with pytest.raises(IntentCoverageDataError, match="cannot be compared with itself"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.run.id,
            baseline_suite_run_id=selected.run.id,
        )
    assert fake.calls == []

    baseline.run.intent_suite_id = uuid.uuid4()
    with pytest.raises(IntentCoverageDataError, match="different suites"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.run.id,
            baseline_suite_run_id=baseline.run.id,
        )


def test_duplicate_and_unreconciled_category_reports_fail_closed() -> None:
    selected, baseline = _reports(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
    )
    duplicate = selected.items[0]
    selected.items = selected.items + (duplicate,)
    with pytest.raises(IntentCoverageDataError, match="duplicate buckets"):
        build_category_comparison(selected, baseline)

    selected, baseline = _reports(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
    )
    selected.totals = _totals(
        intent_count=2,
        product_count=3,
        confident=1,
        non_match=1,
        insufficient=1,
    )
    with pytest.raises(IntentCoverageDataError, match="suite totals"):
        build_category_comparison(selected, baseline)


def test_category_comparison_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
        "compare/{baseline_run_id}/coverage/categories"
    )
    operation = app.openapi()["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith(
        "/IntentCategoryCoverageComparisonResponse"
    )
