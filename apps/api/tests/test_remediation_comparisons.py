from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.db.models.intents import IntentSuiteRun
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    IntentCoverageTotals,
    IntentRemediationPage,
    IntentRemediationPriority,
)
from catora_api.intents.remediation_comparisons import (
    IntentRemediationComparisonService,
    build_remediation_comparison,
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
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"remediation-comparison:{label}"),
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


def _scope(
    *,
    intent_count: int,
    target_count: int,
    product_count: int,
) -> IntentCoverageTotals:
    return IntentCoverageTotals(
        intent_count=intent_count,
        target_count=target_count,
        product_count=product_count,
        confident_match_count=0,
        possible_match_missing_data_count=target_count,
        non_match_count=0,
        insufficient_category_data_count=0,
        confident_coverage_basis_points=0,
    )


def _priority(
    *,
    rank: int,
    field_key: str,
    scope: IntentCoverageTotals,
    intents: int,
    targets: int,
    products: int,
    missing: int,
    conflicting: int = 0,
    category_keys: tuple[str, ...] = (),
    unclassified: int = 0,
) -> IntentRemediationPriority:
    return IntentRemediationPriority(
        priority_rank=rank,
        field_key=field_key,
        affected_intent_count=intents,
        affected_target_count=targets,
        affected_product_count=products,
        intent_impact_basis_points=coverage_basis_points(
            intents,
            scope.intent_count,
        ),
        target_impact_basis_points=coverage_basis_points(
            targets,
            scope.target_count,
        ),
        product_impact_basis_points=coverage_basis_points(
            products,
            scope.product_count,
        ),
        missing_constraint_count=missing,
        conflicting_constraint_count=conflicting,
        category_keys=category_keys,
        unclassified_target_count=unclassified,
    )


def _pages(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    category_bucket: str | None = None,
) -> tuple[IntentRemediationPage, IntentRemediationPage]:
    selected_scope = _scope(intent_count=4, target_count=10, product_count=5)
    baseline_scope = _scope(intent_count=4, target_count=8, product_count=4)
    first_product = str(uuid.UUID(int=1))
    second_product = str(uuid.UUID(int=2))
    selected = IntentRemediationPage(
        run=_suite_run(
            workspace_id=workspace_id,
            suite_id=suite_id,
            label="selected",
            product_ids=[first_product, second_product],
        ),
        items=(
            _priority(
                rank=1,
                field_key="width_mm",
                scope=selected_scope,
                intents=3,
                targets=4,
                products=3,
                missing=3,
                conflicting=1,
                category_keys=("sofas",),
            ),
            _priority(
                rank=2,
                field_key="material",
                scope=selected_scope,
                intents=1,
                targets=2,
                products=1,
                missing=2,
                category_keys=("chairs",),
            ),
        ),
        total=2,
        scope=selected_scope,
        category_bucket=category_bucket,
    )
    baseline = IntentRemediationPage(
        run=_suite_run(
            workspace_id=workspace_id,
            suite_id=suite_id,
            label="baseline",
            product_ids=[first_product],
        ),
        items=(
            _priority(
                rank=1,
                field_key="depth_mm",
                scope=baseline_scope,
                intents=2,
                targets=3,
                products=2,
                missing=3,
                category_keys=("beds",),
            ),
            _priority(
                rank=2,
                field_key="width_mm",
                scope=baseline_scope,
                intents=4,
                targets=5,
                products=4,
                missing=5,
                category_keys=("sofas", "sofa_beds"),
            ),
        ),
        total=2,
        scope=baseline_scope,
        category_bucket=category_bucket,
    )
    return selected, baseline


def test_field_union_presence_rank_and_zero_filled_deltas() -> None:
    selected, baseline = _pages(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
    )

    items = build_remediation_comparison(selected, baseline)

    assert [item.field_key for item in items] == [
        "depth_mm",
        "material",
        "width_mm",
    ]
    assert [item.presence for item in items] == [
        "removed",
        "added",
        "retained",
    ]
    removed, added, retained = items
    assert removed.selected is None
    assert removed.baseline is not None
    assert removed.priority_rank_delta is None
    assert removed.delta.affected_target_count_delta == -3
    assert removed.delta.missing_constraint_count_delta == -3
    assert added.selected is not None
    assert added.baseline is None
    assert added.delta.affected_intent_count_delta == 1
    assert added.delta.target_impact_basis_points_delta == 2_000
    assert retained.priority_rank_delta == -1
    assert retained.delta.affected_intent_count_delta == -1
    assert retained.delta.affected_target_count_delta == -1
    assert retained.delta.conflicting_constraint_count_delta == 1
    assert retained.category_scope_changed is True


class FakeCoverageService:
    def __init__(
        self,
        selected: IntentRemediationPage,
        baseline: IntentRemediationPage,
    ) -> None:
        self.selected = selected
        self.baseline = baseline
        self.calls: list[tuple[uuid.UUID, str | None, int, int]] = []

    async def remediations(
        self,
        _session: object,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
        category_bucket: str | None,
        offset: int,
        limit: int,
    ) -> IntentRemediationPage:
        assert workspace_id == self.selected.run.workspace_id
        self.calls.append((suite_run_id, category_bucket, offset, limit))
        if suite_run_id == self.selected.run.id:
            return self.selected
        return self.baseline


@pytest.mark.asyncio
async def test_service_reuses_category_scope_and_reports_scope_changes() -> None:
    workspace_id = uuid.uuid4()
    selected, baseline = _pages(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
        category_bucket="sofas",
    )
    selected_priority = _priority(
        rank=1,
        field_key="width_mm",
        scope=selected.scope,
        intents=3,
        targets=4,
        products=3,
        missing=4,
        category_keys=("sofas",),
    )
    baseline_priority = _priority(
        rank=1,
        field_key="width_mm",
        scope=baseline.scope,
        intents=4,
        targets=5,
        products=4,
        missing=5,
        category_keys=("sofas",),
    )
    selected = replace(selected, items=(selected_priority,), total=1)
    baseline = replace(baseline, items=(baseline_priority,), total=1)
    fake = FakeCoverageService(selected, baseline)
    service = IntentRemediationComparisonService(cast(Any, fake))

    report = await service.compare(
        cast(Any, object()),
        workspace_id=workspace_id,
        selected_suite_run_id=selected.run.id,
        baseline_suite_run_id=baseline.run.id,
        category_bucket="sofas",
    )

    assert [call[1] for call in fake.calls] == ["sofas", "sofas"]
    assert [call[2:] for call in fake.calls] == [(0, 500), (0, 500)]
    assert report.selection_changed is True
    assert report.category_bucket == "sofas"
    assert report.scope_delta.target_count_delta == 2
    assert report.scope_delta.product_count_delta == 1
    assert report.items[0].category_scope_changed is False


@pytest.mark.asyncio
async def test_self_and_cross_suite_comparisons_fail_closed() -> None:
    workspace_id = uuid.uuid4()
    selected, baseline = _pages(
        workspace_id=workspace_id,
        suite_id=uuid.uuid4(),
    )
    fake = FakeCoverageService(selected, baseline)
    service = IntentRemediationComparisonService(cast(Any, fake))

    with pytest.raises(IntentCoverageDataError, match="cannot be compared with itself"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.run.id,
            baseline_suite_run_id=selected.run.id,
            category_bucket=None,
        )
    assert fake.calls == []

    baseline.run.intent_suite_id = uuid.uuid4()
    with pytest.raises(IntentCoverageDataError, match="different suites"):
        await service.compare(
            cast(Any, object()),
            workspace_id=workspace_id,
            selected_suite_run_id=selected.run.id,
            baseline_suite_run_id=baseline.run.id,
            category_bucket=None,
        )


def test_truncated_rank_and_impact_data_fail_closed() -> None:
    selected, baseline = _pages(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
    )
    truncated = replace(selected, total=3)
    with pytest.raises(IntentCoverageDataError, match="truncated"):
        build_remediation_comparison(truncated, baseline)

    invalid_ranks = replace(
        selected,
        items=(replace(selected.items[0], priority_rank=2), selected.items[1]),
    )
    with pytest.raises(IntentCoverageDataError, match="ranks"):
        build_remediation_comparison(invalid_ranks, baseline)

    invalid_impact = replace(
        selected,
        items=(
            replace(selected.items[0], target_impact_basis_points=9_999),
            selected.items[1],
        ),
    )
    with pytest.raises(IntentCoverageDataError, match="basis points"):
        build_remediation_comparison(invalid_impact, baseline)


def test_remediation_comparison_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/{selected_run_id}/"
        "compare/{baseline_run_id}/coverage/remediations"
    )
    operation = app.openapi()["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/IntentRemediationComparisonResponse")
