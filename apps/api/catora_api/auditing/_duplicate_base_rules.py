from __future__ import annotations

from catora_api.auditing import _structured_base_rules as _base
from catora_api.auditing.structured_rules import (
    evaluate_structured_data_rule,
    is_structured_data_rule,
)
from catora_api.auditing.types import ProductAuditSnapshot, RuleEvaluation

SEVERITY_WEIGHTS = _base.SEVERITY_WEIGHTS
RuleSpecificationError = _base.RuleSpecificationError
TaxonomyFieldRule = _base.TaxonomyFieldRule
finding_fingerprint = _base.finding_fingerprint
_evaluate_relationships = _base._evaluate_relationships


def evaluate_product(
    snapshot: ProductAuditSnapshot,
    rules: tuple[TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    base_rules = tuple(rule for rule in rules if not is_structured_data_rule(rule))
    structured_rules = tuple(rule for rule in rules if is_structured_data_rule(rule))
    evaluations = list(_base.evaluate_product(snapshot, base_rules))
    evaluations.extend(
        evaluation
        for rule in structured_rules
        if rule.category_key == snapshot.category_key
        for evaluation in evaluate_structured_data_rule(snapshot, rule)
    )
    return tuple(evaluations)


def evaluate_catalog(
    snapshots: tuple[ProductAuditSnapshot, ...],
    rules: tuple[TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    return tuple(
        evaluation
        for snapshot in snapshots
        for evaluation in evaluate_product(snapshot, rules)
    )
