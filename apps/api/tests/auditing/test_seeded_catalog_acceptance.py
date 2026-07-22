from __future__ import annotations

import uuid
from collections.abc import Sequence

from catora_api.auditing.incremental import merge_score_contributions
from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_catalog
from catora_api.auditing.scoring import (
    calculate_health_from_contributions,
    calculate_health_score,
)
from catora_api.auditing.types import AttributeSnapshot, ProductAuditSnapshot, RuleEvaluation

_PRODUCT_NAMESPACE = uuid.UUID("c9883607-4f17-4e15-872a-158d0e2c17ae")
_RULE_VERSION_ID = uuid.UUID("eb3408f3-9b5d-4fd1-a637-a8f0a586c358")
_PRODUCT_COUNT = 100
_CHANGED_PRODUCT_INDEXES = frozenset(range(10))


def _width_rule() -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=_RULE_VERSION_ID,
        rule_key="tax.sofas_sectionals.width_mm",
        rule_version="1.0.0",
        specification={
            "category_key": "sofas_sectionals",
            "field_key": "width_mm",
            "requirement": "required",
            "severity": "high",
            "field": {
                "category_key": "sofas_sectionals",
                "key": "width_mm",
                "label": "Width",
                "scope": "product",
                "data_type": "decimal",
                "canonical_unit": "mm",
                "allowed_values": [],
                "markets": [],
                "constraints": {"minimum": 1, "maximum": 20000},
                "mapping": {},
            },
        },
    )


def _product_id(index: int) -> uuid.UUID:
    return uuid.uuid5(_PRODUCT_NAMESPACE, f"seeded-product-{index:03d}")


def _catalog(*, resolve_changed_missing_values: bool = False) -> tuple[ProductAuditSnapshot, ...]:
    snapshots: list[ProductAuditSnapshot] = []
    for index in range(_PRODUCT_COUNT):
        missing = index % 5 == 0
        if resolve_changed_missing_values and index in _CHANGED_PRODUCT_INDEXES:
            missing = False
        attributes = {}
        if not missing:
            attributes["width_mm"] = AttributeSnapshot(
                key="width_mm",
                value=1800.0 + index,
                value_type="decimal",
                unit="mm",
            )
        snapshots.append(
            ProductAuditSnapshot(
                product_id=_product_id(index),
                category_key="sofas_sectionals",
                attributes=attributes,
                source_coverage_basis_points=10000,
            )
        )
    return tuple(snapshots)


def _findings(
    evaluations: Sequence[RuleEvaluation],
) -> frozenset[tuple[str, str]]:
    return frozenset(
        (str(evaluation.product_id), evaluation.finding.fingerprint)
        for evaluation in evaluations
        if evaluation.finding is not None
    )


def test_seeded_100_product_catalog_is_reproducible_with_fixed_totals() -> None:
    rule = _width_rule()
    snapshots = _catalog()

    first = evaluate_catalog(snapshots, (rule,))
    second = evaluate_catalog(snapshots, (rule,))
    first_health = calculate_health_score(first)
    second_health = calculate_health_score(second)

    assert first == second
    assert first_health == second_health
    assert len(first) == 180
    assert len(_findings(first)) == 20
    assert first_health.overall.eligible_weight == 10800
    assert first_health.overall.evaluated_weight == 10800
    assert first_health.overall.passed_weight == 9600
    assert first_health.overall.score_basis_points == 8889
    assert first_health.overall.confidence_basis_points == 10000


def test_incremental_contribution_and_finding_merge_matches_full_rerun() -> None:
    rule = _width_rule()
    baseline_snapshots = _catalog()
    updated_snapshots = _catalog(resolve_changed_missing_values=True)
    target_product_ids = {
        str(_product_id(index)) for index in _CHANGED_PRODUCT_INDEXES
    }
    changed_snapshots = tuple(
        snapshot
        for snapshot in updated_snapshots
        if str(snapshot.product_id) in target_product_ids
    )

    baseline_evaluations = evaluate_catalog(baseline_snapshots, (rule,))
    changed_evaluations = evaluate_catalog(changed_snapshots, (rule,))
    full_evaluations = evaluate_catalog(updated_snapshots, (rule,))

    merged_contributions = merge_score_contributions(
        calculate_health_score(baseline_evaluations).overall.contributions,
        target_product_ids=target_product_ids,
        current=calculate_health_score(changed_evaluations).overall.contributions,
    )
    incremental_health = calculate_health_from_contributions(merged_contributions)
    full_health = calculate_health_score(full_evaluations)

    retained_findings = frozenset(
        finding
        for finding in _findings(baseline_evaluations)
        if finding[0] not in target_product_ids
    )
    incremental_findings = retained_findings | _findings(changed_evaluations)

    assert incremental_health == full_health
    assert incremental_findings == _findings(full_evaluations)
    assert len(full_evaluations) == 182
    assert len(incremental_findings) == 18
    assert full_health.overall.eligible_weight == 10920
    assert full_health.overall.evaluated_weight == 10920
    assert full_health.overall.passed_weight == 9840
    assert full_health.overall.score_basis_points == 9011
    assert full_health.overall.confidence_basis_points == 10000
