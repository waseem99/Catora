from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from catora_api.auditing import _field_rules as _base
from catora_api.auditing.types import (
    AttributeSnapshot,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
    ScoreDimension,
)

SEVERITY_WEIGHTS = _base.SEVERITY_WEIGHTS
RuleSpecificationError = _base.RuleSpecificationError
finding_fingerprint = _base.finding_fingerprint

_RELATIONSHIP_CONSTRAINT_KEYS = (
    "less_than_or_equal_to_field",
    "greater_than_or_equal_to_field",
    "matches_product_field",
)
_FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class TaxonomyFieldRule(_base.TaxonomyFieldRule):
    @classmethod
    def from_specification(
        cls,
        *,
        rule_version_id: uuid.UUID,
        rule_key: str,
        rule_version: str,
        specification: Mapping[str, object],
    ) -> TaxonomyFieldRule:
        parsed = _base.TaxonomyFieldRule.from_specification(
            rule_version_id=rule_version_id,
            rule_key=rule_key,
            rule_version=rule_version,
            specification=specification,
        )
        _validate_relationship_contract(
            field_key=parsed.field_key,
            scope=parsed.scope,
            data_type=parsed.data_type,
            constraints=parsed.constraints,
        )
        return cls(
            rule_version_id=parsed.rule_version_id,
            rule_key=parsed.rule_key,
            rule_version=parsed.rule_version,
            category_key=parsed.category_key,
            field_key=parsed.field_key,
            field_label=parsed.field_label,
            requirement=parsed.requirement,
            severity=parsed.severity,
            scope=parsed.scope,
            data_type=parsed.data_type,
            canonical_unit=parsed.canonical_unit,
            allowed_values=parsed.allowed_values,
            markets=parsed.markets,
            constraints=parsed.constraints,
            mapping=parsed.mapping,
        )

    @property
    def has_relationship_constraints(self) -> bool:
        return any(
            self.constraints.get(key) is not None
            for key in _RELATIONSHIP_CONSTRAINT_KEYS
        )


def evaluate_product(
    snapshot: ProductAuditSnapshot,
    rules: tuple[TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    base_evaluations = _base.evaluate_product(snapshot, rules)
    relationship_evaluations = tuple(
        evaluation
        for rule in rules
        if rule.category_key == snapshot.category_key
        for evaluation in _evaluate_relationships(snapshot, rule)
    )
    return (*base_evaluations, *relationship_evaluations)


def evaluate_catalog(
    snapshots: tuple[ProductAuditSnapshot, ...],
    rules: tuple[TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    return tuple(
        evaluation
        for snapshot in snapshots
        for evaluation in evaluate_product(snapshot, rules)
    )


def _evaluate_relationships(
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
) -> tuple[RuleEvaluation, ...]:
    if not rule.has_relationship_constraints:
        return ()
    evaluations: list[RuleEvaluation] = []
    for variant_id, attributes in _relationship_targets(snapshot, rule):
        if not _relationship_applies(rule, variant_id):
            continue
        attribute = attributes.get(rule.field_key)
        if not _present(attribute) or attribute is None:
            evaluations.append(_not_evaluated(snapshot, rule, variant_id))
            continue
        if _base._validation_failures(attribute, rule):
            evaluations.append(_not_evaluated(snapshot, rule, variant_id))
            continue
        evaluations.append(
            _relationship_evaluation(
                snapshot=snapshot,
                rule=rule,
                variant_id=variant_id,
                attribute=attribute,
                attributes=attributes,
            )
        )
    return tuple(evaluations)


def _relationship_targets(
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
) -> tuple[tuple[uuid.UUID | None, Mapping[str, AttributeSnapshot]], ...]:
    if rule.scope == "product":
        return ((None, snapshot.attributes),)
    if rule.scope == "variant":
        return tuple(
            (variant.variant_id, variant.attributes) for variant in snapshot.variants
        )
    if rule.scope == "both":
        return (
            (None, snapshot.attributes),
            *(
                (variant.variant_id, variant.attributes)
                for variant in snapshot.variants
            ),
        )
    raise RuleSpecificationError(f"unsupported field scope {rule.scope!r}")


def _relationship_applies(
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
) -> bool:
    if any(
        rule.constraints.get(key) is not None
        for key in (
            "less_than_or_equal_to_field",
            "greater_than_or_equal_to_field",
        )
    ):
        return True
    return (
        variant_id is not None
        and rule.constraints.get("matches_product_field") is not None
    )


def _relationship_evaluation(
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot,
    attributes: Mapping[str, AttributeSnapshot],
) -> RuleEvaluation:
    failures: list[str] = []
    unavailable = False
    for constraint_key, failure_code, comparison in (
        ("less_than_or_equal_to_field", "above_related_field", "less_or_equal"),
        (
            "greater_than_or_equal_to_field",
            "below_related_field",
            "greater_or_equal",
        ),
    ):
        related_key = _optional_relationship_field(rule.constraints, constraint_key)
        if related_key is None:
            continue
        related = attributes.get(related_key)
        if not _present(related):
            unavailable = True
            continue
        assert related is not None
        relation_failure = _numeric_relationship_failure(
            attribute,
            related,
            comparison=comparison,
            comparison_failure=failure_code,
        )
        if relation_failure is not None:
            failures.append(relation_failure)

    product_field_key = _optional_relationship_field(
        rule.constraints,
        "matches_product_field",
    )
    if product_field_key is not None and variant_id is not None:
        product_attribute = snapshot.attributes.get(product_field_key)
        if not _present(product_attribute):
            unavailable = True
        elif product_attribute is not None and not _attributes_match(
            attribute,
            product_attribute,
        ):
            failures.append("product_variant_mismatch")

    codes = tuple(sorted(set(failures)))
    if codes:
        return _relationship_result(
            snapshot=snapshot,
            rule=rule,
            variant_id=variant_id,
            attribute=attribute,
            outcome="failed",
            failure_codes=codes,
        )
    if unavailable:
        return _not_evaluated(snapshot, rule, variant_id)
    return _relationship_result(
        snapshot=snapshot,
        rule=rule,
        variant_id=variant_id,
        attribute=attribute,
        outcome="passed",
        failure_codes=(),
    )


def _relationship_result(
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot,
    outcome: Literal["passed", "failed"],
    failure_codes: tuple[str, ...],
) -> RuleEvaluation:
    finding: FindingCandidate | None = None
    if failure_codes:
        finding = FindingCandidate(
            fingerprint=finding_fingerprint(
                rule_version_id=rule.rule_version_id,
                product_id=snapshot.product_id,
                variant_id=variant_id,
                field_key=rule.field_key,
                check_key="cross_field_consistency",
                failure_codes=failure_codes,
            ),
            rule_version_id=rule.rule_version_id,
            product_id=snapshot.product_id,
            variant_id=variant_id,
            severity=rule.severity,
            title=f"{rule.field_label}: inconsistent related values",
            explanation=(
                f"{rule.field_label} failed deterministic cross-field checks: "
                + ", ".join(failure_codes)
            ),
            field_key=rule.field_key,
            affected_value=attribute.value,
            evidence=attribute.evidence,
            business_impact="data_quality",
            remediation_type="reconcile_related_values",
            failure_codes=failure_codes,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        field_key=rule.field_key,
        check_key="cross_field_consistency",
        dimension=_relationship_dimension(variant_id),
        severity=rule.severity,
        weight=rule.weight,
        outcome=outcome,
        coverage_basis_points=snapshot.source_coverage_basis_points,
        finding=finding,
    )


def _not_evaluated(
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        field_key=rule.field_key,
        check_key="cross_field_consistency",
        dimension=_relationship_dimension(variant_id),
        severity=rule.severity,
        weight=rule.weight,
        outcome="not_evaluated",
        coverage_basis_points=snapshot.source_coverage_basis_points,
    )


def _relationship_dimension(variant_id: uuid.UUID | None) -> ScoreDimension:
    return "variant_quality" if variant_id is not None else "consistency"


def _numeric_relationship_failure(
    attribute: AttributeSnapshot,
    related: AttributeSnapshot,
    *,
    comparison: str,
    comparison_failure: str,
) -> str | None:
    left = _optional_number(attribute.value)
    right = _optional_number(related.value)
    if left is None or right is None:
        return "related_field_not_comparable"
    if attribute.unit != related.unit:
        return "related_field_unit_mismatch"
    if comparison == "less_or_equal":
        return None if left <= right else comparison_failure
    if comparison == "greater_or_equal":
        return None if left >= right else comparison_failure
    raise RuleSpecificationError(f"unsupported relationship comparison {comparison!r}")


def _attributes_match(left: AttributeSnapshot, right: AttributeSnapshot) -> bool:
    return (
        left.value == right.value
        and left.value_type == right.value_type
        and left.unit == right.unit
        and left.locale == right.locale
    )


def _present(attribute: AttributeSnapshot | None) -> bool:
    return (
        attribute is not None
        and attribute.value_state == "present"
        and attribute.value is not None
    )


def _validate_relationship_contract(
    *,
    field_key: str,
    scope: str,
    data_type: str,
    constraints: Mapping[str, object],
) -> None:
    for constraint_key in _RELATIONSHIP_CONSTRAINT_KEYS:
        related_key = _optional_relationship_field(constraints, constraint_key)
        if related_key is None:
            continue
        if (
            constraint_key
            in {
                "less_than_or_equal_to_field",
                "greater_than_or_equal_to_field",
            }
            and related_key == field_key
        ):
            raise RuleSpecificationError(
                f"relationship constraint {constraint_key!r} cannot reference its own field"
            )
        if (
            constraint_key
            in {
                "less_than_or_equal_to_field",
                "greater_than_or_equal_to_field",
            }
            and data_type not in {"integer", "decimal"}
        ):
            raise RuleSpecificationError(
                f"relationship constraint {constraint_key!r} requires a numeric field"
            )
        if constraint_key == "matches_product_field" and scope == "product":
            raise RuleSpecificationError(
                "matches_product_field requires variant or both field scope"
            )


def _optional_relationship_field(
    constraints: Mapping[str, object],
    key: str,
) -> str | None:
    value = constraints.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or _FIELD_KEY_PATTERN.fullmatch(value) is None:
        raise RuleSpecificationError(
            f"relationship constraint {key!r} must be a canonical field key"
        )
    return value


def _optional_number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None
