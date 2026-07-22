from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.intents.category_comparisons import (
    IntentCoverageDelta,
    coverage_delta,
)
from catora_api.intents.coverage import (
    UNCLASSIFIED_CATEGORY_BUCKET,
    IntentCoverageDataError,
    IntentCoverageService,
    IntentCoverageTotals,
    IntentRemediationPage,
    IntentRemediationPriority,
)
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    _validated_source,
)
from catora_api.intents.suites import coverage_basis_points

RemediationPresence = Literal["retained", "added", "removed"]
_MAX_REMEDIATION_FIELDS = 500


@dataclass(frozen=True, slots=True)
class IntentRemediationDelta:
    affected_intent_count_delta: int
    affected_target_count_delta: int
    affected_product_count_delta: int
    intent_impact_basis_points_delta: int
    target_impact_basis_points_delta: int
    product_impact_basis_points_delta: int
    missing_constraint_count_delta: int
    conflicting_constraint_count_delta: int
    unclassified_target_count_delta: int


@dataclass(frozen=True, slots=True)
class IntentRemediationComparisonItem:
    field_key: str
    presence: RemediationPresence
    selected: IntentRemediationPriority | None
    baseline: IntentRemediationPriority | None
    priority_rank_delta: int | None
    category_scope_changed: bool
    delta: IntentRemediationDelta


@dataclass(frozen=True, slots=True)
class IntentRemediationComparisonReport:
    selected: IntentRemediationPage
    baseline: IntentRemediationPage
    selection_changed: bool
    category_bucket: str | None
    items: tuple[IntentRemediationComparisonItem, ...]
    scope_delta: IntentCoverageDelta


class IntentRemediationComparisonService:
    def __init__(self, coverage_service: IntentCoverageService | None = None) -> None:
        self.coverage_service = coverage_service or IntentCoverageService()

    async def compare(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        selected_suite_run_id: uuid.UUID,
        baseline_suite_run_id: uuid.UUID,
        category_bucket: str | None,
    ) -> IntentRemediationComparisonReport:
        if selected_suite_run_id == baseline_suite_run_id:
            raise IntentCoverageDataError(
                "An intent suite run cannot be compared with itself"
            )
        selected = await self.coverage_service.remediations(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_suite_run_id,
            category_bucket=category_bucket,
            offset=0,
            limit=_MAX_REMEDIATION_FIELDS,
        )
        baseline = await self.coverage_service.remediations(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_suite_run_id,
            category_bucket=category_bucket,
            offset=0,
            limit=_MAX_REMEDIATION_FIELDS,
        )
        if selected.run.intent_suite_id != baseline.run.intent_suite_id:
            raise IntentCoverageDataError(
                "Intent suite runs belong to different suites"
            )
        if selected.category_bucket != category_bucket:
            raise IntentCoverageDataError(
                "Selected remediation category scope does not reconcile"
            )
        if baseline.category_bucket != category_bucket:
            raise IntentCoverageDataError(
                "Baseline remediation category scope does not reconcile"
            )

        selected_products = _validated_products(selected, label="Selected")
        baseline_products = _validated_products(baseline, label="Baseline")
        return IntentRemediationComparisonReport(
            selected=selected,
            baseline=baseline,
            selection_changed=selected_products != baseline_products,
            category_bucket=category_bucket,
            items=build_remediation_comparison(selected, baseline),
            scope_delta=coverage_delta(selected.scope, baseline.scope),
        )


def build_remediation_comparison(
    selected: IntentRemediationPage,
    baseline: IntentRemediationPage,
) -> tuple[IntentRemediationComparisonItem, ...]:
    selected_by_field = _validated_remediation_map(selected, label="Selected")
    baseline_by_field = _validated_remediation_map(baseline, label="Baseline")
    field_keys = sorted(set(selected_by_field) | set(baseline_by_field))
    items: list[IntentRemediationComparisonItem] = []
    for field_key in field_keys:
        selected_item = selected_by_field.get(field_key)
        baseline_item = baseline_by_field.get(field_key)
        if selected_item is not None and baseline_item is not None:
            presence: RemediationPresence = "retained"
            priority_rank_delta = (
                selected_item.priority_rank - baseline_item.priority_rank
            )
        elif selected_item is not None:
            presence = "added"
            priority_rank_delta = None
        else:
            presence = "removed"
            priority_rank_delta = None
        items.append(
            IntentRemediationComparisonItem(
                field_key=field_key,
                presence=presence,
                selected=selected_item,
                baseline=baseline_item,
                priority_rank_delta=priority_rank_delta,
                category_scope_changed=(
                    _category_scope(selected_item)
                    != _category_scope(baseline_item)
                ),
                delta=remediation_delta(selected_item, baseline_item),
            )
        )
    return tuple(items)


def remediation_delta(
    selected: IntentRemediationPriority | None,
    baseline: IntentRemediationPriority | None,
) -> IntentRemediationDelta:
    return IntentRemediationDelta(
        affected_intent_count_delta=_value(selected, "affected_intent_count")
        - _value(baseline, "affected_intent_count"),
        affected_target_count_delta=_value(selected, "affected_target_count")
        - _value(baseline, "affected_target_count"),
        affected_product_count_delta=_value(selected, "affected_product_count")
        - _value(baseline, "affected_product_count"),
        intent_impact_basis_points_delta=_value(
            selected,
            "intent_impact_basis_points",
        )
        - _value(baseline, "intent_impact_basis_points"),
        target_impact_basis_points_delta=_value(
            selected,
            "target_impact_basis_points",
        )
        - _value(baseline, "target_impact_basis_points"),
        product_impact_basis_points_delta=_value(
            selected,
            "product_impact_basis_points",
        )
        - _value(baseline, "product_impact_basis_points"),
        missing_constraint_count_delta=_value(
            selected,
            "missing_constraint_count",
        )
        - _value(baseline, "missing_constraint_count"),
        conflicting_constraint_count_delta=_value(
            selected,
            "conflicting_constraint_count",
        )
        - _value(baseline, "conflicting_constraint_count"),
        unclassified_target_count_delta=_value(
            selected,
            "unclassified_target_count",
        )
        - _value(baseline, "unclassified_target_count"),
    )


def _value(item: IntentRemediationPriority | None, attribute: str) -> int:
    if item is None:
        return 0
    value = getattr(item, attribute)
    if not isinstance(value, int):
        raise IntentCoverageDataError("Stored remediation value is invalid")
    return value


def _category_scope(
    item: IntentRemediationPriority | None,
) -> tuple[str, ...]:
    if item is None:
        return ()
    if item.unclassified_target_count:
        return (*item.category_keys, UNCLASSIFIED_CATEGORY_BUCKET)
    return item.category_keys


def _validated_products(
    page: IntentRemediationPage,
    *,
    label: str,
) -> tuple[uuid.UUID, ...]:
    try:
        _snapshot_hash, product_ids = _validated_source(page.run)
    except IntentSuiteHistoryRerunConflictError as exc:
        raise IntentCoverageDataError(
            f"{label} intent suite run history is invalid: {exc}"
        ) from exc
    return product_ids


def _validated_remediation_map(
    page: IntentRemediationPage,
    *,
    label: str,
) -> dict[str, IntentRemediationPriority]:
    _validate_scope(page.scope, label=f"{label} remediation scope")
    if page.total != len(page.items):
        raise IntentCoverageDataError(
            f"{label} remediation priorities are truncated"
        )
    if page.total > _MAX_REMEDIATION_FIELDS:
        raise IntentCoverageDataError(
            f"{label} remediation priorities exceed the comparison limit"
        )
    ranks = tuple(item.priority_rank for item in page.items)
    if ranks != tuple(range(1, len(page.items) + 1)):
        raise IntentCoverageDataError(
            f"{label} remediation priority ranks do not reconcile"
        )

    by_field: dict[str, IntentRemediationPriority] = {}
    for item in page.items:
        if item.field_key in by_field:
            raise IntentCoverageDataError(
                f"{label} remediation priorities contain duplicate fields"
            )
        _validate_priority(item, scope=page.scope, label=label)
        _validate_category_filter(
            item,
            category_bucket=page.category_bucket,
            label=label,
        )
        by_field[item.field_key] = item
    return by_field


def _validate_scope(scope: IntentCoverageTotals, *, label: str) -> None:
    counts = (
        scope.intent_count,
        scope.target_count,
        scope.product_count,
        scope.confident_match_count,
        scope.possible_match_missing_data_count,
        scope.non_match_count,
        scope.insufficient_category_data_count,
    )
    if any(value < 0 for value in counts):
        raise IntentCoverageDataError(f"{label} contains negative counts")
    state_total = (
        scope.confident_match_count
        + scope.possible_match_missing_data_count
        + scope.non_match_count
        + scope.insufficient_category_data_count
    )
    if state_total != scope.target_count:
        raise IntentCoverageDataError(f"{label} match states do not reconcile")
    if scope.confident_coverage_basis_points != coverage_basis_points(
        scope.confident_match_count,
        scope.target_count,
    ):
        raise IntentCoverageDataError(f"{label} coverage does not reconcile")


def _validate_priority(
    item: IntentRemediationPriority,
    *,
    scope: IntentCoverageTotals,
    label: str,
) -> None:
    counts = (
        item.affected_intent_count,
        item.affected_target_count,
        item.affected_product_count,
        item.missing_constraint_count,
        item.conflicting_constraint_count,
        item.unclassified_target_count,
    )
    if any(value < 0 for value in counts):
        raise IntentCoverageDataError(
            f"{label} remediation priority contains negative counts"
        )
    if item.affected_intent_count > scope.intent_count:
        raise IntentCoverageDataError(
            f"{label} remediation intent impact exceeds its scope"
        )
    if item.affected_target_count > scope.target_count:
        raise IntentCoverageDataError(
            f"{label} remediation target impact exceeds its scope"
        )
    if item.affected_product_count > scope.product_count:
        raise IntentCoverageDataError(
            f"{label} remediation product impact exceeds its scope"
        )
    if item.unclassified_target_count > item.affected_target_count:
        raise IntentCoverageDataError(
            f"{label} remediation unclassified impact does not reconcile"
        )
    if item.missing_constraint_count + item.conflicting_constraint_count <= 0:
        raise IntentCoverageDataError(
            f"{label} remediation priority has no affected constraints"
        )
    expected_impacts = (
        coverage_basis_points(item.affected_intent_count, scope.intent_count),
        coverage_basis_points(item.affected_target_count, scope.target_count),
        coverage_basis_points(item.affected_product_count, scope.product_count),
    )
    actual_impacts = (
        item.intent_impact_basis_points,
        item.target_impact_basis_points,
        item.product_impact_basis_points,
    )
    if actual_impacts != expected_impacts:
        raise IntentCoverageDataError(
            f"{label} remediation impact basis points do not reconcile"
        )
    if item.category_keys != tuple(sorted(set(item.category_keys))):
        raise IntentCoverageDataError(
            f"{label} remediation category keys are not canonical"
        )


def _validate_category_filter(
    item: IntentRemediationPriority,
    *,
    category_bucket: str | None,
    label: str,
) -> None:
    if category_bucket is None:
        return
    if category_bucket == UNCLASSIFIED_CATEGORY_BUCKET:
        if item.category_keys or (
            item.unclassified_target_count != item.affected_target_count
        ):
            raise IntentCoverageDataError(
                f"{label} unclassified remediation scope does not reconcile"
            )
        return
    if item.category_keys != (category_bucket,) or item.unclassified_target_count:
        raise IntentCoverageDataError(
            f"{label} remediation category scope does not reconcile"
        )
