from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.intents.coverage import (
    IntentCategoryCoverage,
    IntentCategoryCoverageReport,
    IntentCoverageDataError,
    IntentCoverageService,
    IntentCoverageTotals,
)
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    _validated_source,
)
from catora_api.intents.suites import coverage_basis_points

CategoryPresence = Literal["retained", "added", "removed"]


@dataclass(frozen=True, slots=True)
class IntentCoverageDelta:
    intent_count_delta: int
    target_count_delta: int
    product_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


@dataclass(frozen=True, slots=True)
class IntentCategoryCoverageComparisonItem:
    category_key: str | None
    presence: CategoryPresence
    selected: IntentCategoryCoverage | None
    baseline: IntentCategoryCoverage | None
    delta: IntentCoverageDelta


@dataclass(frozen=True, slots=True)
class IntentCategoryCoverageComparisonReport:
    selected: IntentCategoryCoverageReport
    baseline: IntentCategoryCoverageReport
    selection_changed: bool
    items: tuple[IntentCategoryCoverageComparisonItem, ...]
    totals_delta: IntentCoverageDelta


class IntentCategoryCoverageComparisonService:
    def __init__(self, coverage_service: IntentCoverageService | None = None) -> None:
        self.coverage_service = coverage_service or IntentCoverageService()

    async def compare(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        selected_suite_run_id: uuid.UUID,
        baseline_suite_run_id: uuid.UUID,
    ) -> IntentCategoryCoverageComparisonReport:
        if selected_suite_run_id == baseline_suite_run_id:
            raise IntentCoverageDataError(
                "An intent suite run cannot be compared with itself"
            )
        selected = await self.coverage_service.category_coverage(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_suite_run_id,
        )
        baseline = await self.coverage_service.category_coverage(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_suite_run_id,
        )
        if selected.run.intent_suite_id != baseline.run.intent_suite_id:
            raise IntentCoverageDataError(
                "Intent suite runs belong to different suites"
            )

        selected_products = _validated_products(selected, label="Selected")
        baseline_products = _validated_products(baseline, label="Baseline")
        return IntentCategoryCoverageComparisonReport(
            selected=selected,
            baseline=baseline,
            selection_changed=selected_products != baseline_products,
            items=build_category_comparison(selected, baseline),
            totals_delta=coverage_delta(selected.totals, baseline.totals),
        )


def build_category_comparison(
    selected: IntentCategoryCoverageReport,
    baseline: IntentCategoryCoverageReport,
) -> tuple[IntentCategoryCoverageComparisonItem, ...]:
    selected_by_key = _validated_category_map(selected, label="Selected")
    baseline_by_key = _validated_category_map(baseline, label="Baseline")
    category_keys = set(selected_by_key) | set(baseline_by_key)
    items: list[IntentCategoryCoverageComparisonItem] = []
    for category_key in sorted(
        category_keys,
        key=lambda value: (value is None, value or ""),
    ):
        selected_item = selected_by_key.get(category_key)
        baseline_item = baseline_by_key.get(category_key)
        if selected_item is not None and baseline_item is not None:
            presence: CategoryPresence = "retained"
        elif selected_item is not None:
            presence = "added"
        else:
            presence = "removed"
        selected_totals = _category_totals(
            selected_item or _empty_category(category_key)
        )
        baseline_totals = _category_totals(
            baseline_item or _empty_category(category_key)
        )
        items.append(
            IntentCategoryCoverageComparisonItem(
                category_key=category_key,
                presence=presence,
                selected=selected_item,
                baseline=baseline_item,
                delta=coverage_delta(selected_totals, baseline_totals),
            )
        )
    return tuple(items)


def coverage_delta(
    selected: IntentCoverageTotals,
    baseline: IntentCoverageTotals,
) -> IntentCoverageDelta:
    return IntentCoverageDelta(
        intent_count_delta=selected.intent_count - baseline.intent_count,
        target_count_delta=selected.target_count - baseline.target_count,
        product_count_delta=selected.product_count - baseline.product_count,
        confident_match_count_delta=(
            selected.confident_match_count - baseline.confident_match_count
        ),
        possible_match_missing_data_count_delta=(
            selected.possible_match_missing_data_count
            - baseline.possible_match_missing_data_count
        ),
        non_match_count_delta=selected.non_match_count - baseline.non_match_count,
        insufficient_category_data_count_delta=(
            selected.insufficient_category_data_count
            - baseline.insufficient_category_data_count
        ),
        confident_coverage_basis_points_delta=(
            selected.confident_coverage_basis_points
            - baseline.confident_coverage_basis_points
        ),
    )


def _validated_products(
    report: IntentCategoryCoverageReport,
    *,
    label: str,
) -> tuple[uuid.UUID, ...]:
    try:
        _snapshot_hash, product_ids = _validated_source(report.run)
    except IntentSuiteHistoryRerunConflictError as exc:
        raise IntentCoverageDataError(
            f"{label} intent suite run history is invalid: {exc}"
        ) from exc
    return product_ids


def _validated_category_map(
    report: IntentCategoryCoverageReport,
    *,
    label: str,
) -> dict[str | None, IntentCategoryCoverage]:
    _validate_totals(report.totals, label=f"{label} suite totals")
    by_key: dict[str | None, IntentCategoryCoverage] = {}
    target_count = 0
    confident_count = 0
    possible_count = 0
    non_match_count = 0
    insufficient_count = 0
    for item in report.items:
        if item.category_key in by_key:
            raise IntentCoverageDataError(
                f"{label} category coverage contains duplicate buckets"
            )
        totals = _category_totals(item)
        _validate_totals(totals, label=f"{label} category coverage")
        by_key[item.category_key] = item
        target_count += item.target_count
        confident_count += item.confident_match_count
        possible_count += item.possible_match_missing_data_count
        non_match_count += item.non_match_count
        insufficient_count += item.insufficient_category_data_count
    expected = report.totals
    if (
        target_count != expected.target_count
        or confident_count != expected.confident_match_count
        or possible_count != expected.possible_match_missing_data_count
        or non_match_count != expected.non_match_count
        or insufficient_count != expected.insufficient_category_data_count
    ):
        raise IntentCoverageDataError(
            f"{label} category coverage does not reconcile with suite totals"
        )
    return by_key


def _validate_totals(totals: IntentCoverageTotals, *, label: str) -> None:
    values = (
        totals.intent_count,
        totals.target_count,
        totals.product_count,
        totals.confident_match_count,
        totals.possible_match_missing_data_count,
        totals.non_match_count,
        totals.insufficient_category_data_count,
    )
    if any(value < 0 for value in values):
        raise IntentCoverageDataError(f"{label} contains negative counts")
    state_total = (
        totals.confident_match_count
        + totals.possible_match_missing_data_count
        + totals.non_match_count
        + totals.insufficient_category_data_count
    )
    if state_total != totals.target_count:
        raise IntentCoverageDataError(f"{label} match states do not reconcile")
    expected_coverage = coverage_basis_points(
        totals.confident_match_count,
        totals.target_count,
    )
    if totals.confident_coverage_basis_points != expected_coverage:
        raise IntentCoverageDataError(f"{label} coverage does not reconcile")


def _category_totals(item: IntentCategoryCoverage) -> IntentCoverageTotals:
    return IntentCoverageTotals(
        intent_count=item.intent_count,
        target_count=item.target_count,
        product_count=item.product_count,
        confident_match_count=item.confident_match_count,
        possible_match_missing_data_count=(
            item.possible_match_missing_data_count
        ),
        non_match_count=item.non_match_count,
        insufficient_category_data_count=(
            item.insufficient_category_data_count
        ),
        confident_coverage_basis_points=item.confident_coverage_basis_points,
    )


def _empty_category(category_key: str | None) -> IntentCategoryCoverage:
    return IntentCategoryCoverage(
        category_key=category_key,
        intent_count=0,
        target_count=0,
        product_count=0,
        confident_match_count=0,
        possible_match_missing_data_count=0,
        non_match_count=0,
        insufficient_category_data_count=0,
        confident_coverage_basis_points=0,
    )
