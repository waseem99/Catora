from __future__ import annotations

from catora_api.auditing import _image_base_rules as _base
from catora_api.auditing.image_rules import (
    evaluate_image_quality_rule,
    is_image_quality_rule,
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
    base_rules = tuple(rule for rule in rules if not is_image_quality_rule(rule))
    image_rules = tuple(rule for rule in rules if is_image_quality_rule(rule))
    evaluations = list(_base.evaluate_product(snapshot, base_rules))
    evaluations.extend(
        evaluate_image_quality_rule(snapshot, rule)
        for rule in image_rules
        if rule.category_key == snapshot.category_key
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
