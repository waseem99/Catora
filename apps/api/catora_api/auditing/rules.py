from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import cast
from urllib.parse import urlsplit

from catora_api.auditing.types import (
    AttributeSnapshot,
    AttributeValue,
    EvaluationOutcome,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
    ScoreDimension,
    Severity,
)

SEVERITY_WEIGHTS: dict[Severity, int] = {
    "critical": 100,
    "high": 60,
    "medium": 30,
    "low": 10,
    "informational": 5,
}


class RuleSpecificationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaxonomyFieldRule:
    rule_version_id: uuid.UUID
    rule_key: str
    rule_version: str
    category_key: str
    field_key: str
    field_label: str
    requirement: str
    severity: Severity
    scope: str
    data_type: str
    canonical_unit: str | None
    allowed_values: tuple[str, ...]
    markets: tuple[str, ...]
    constraints: Mapping[str, object]
    mapping: Mapping[str, object]

    @classmethod
    def from_specification(
        cls,
        *,
        rule_version_id: uuid.UUID,
        rule_key: str,
        rule_version: str,
        specification: Mapping[str, object],
    ) -> TaxonomyFieldRule:
        category_key = _required_str(specification, "category_key")
        field_key = _required_str(specification, "field_key")
        requirement = _required_str(specification, "requirement")
        if requirement not in {"required", "recommended"}:
            raise RuleSpecificationError(
                f"unsupported taxonomy requirement {requirement!r}"
            )
        severity = _severity(_required_str(specification, "severity"))
        field_spec = _required_mapping(specification, "field")
        if _required_str(field_spec, "category_key") != category_key:
            raise RuleSpecificationError("field category_key does not match rule category_key")
        if _required_str(field_spec, "key") != field_key:
            raise RuleSpecificationError("field key does not match rule field_key")
        return cls(
            rule_version_id=rule_version_id,
            rule_key=rule_key,
            rule_version=rule_version,
            category_key=category_key,
            field_key=field_key,
            field_label=_required_str(field_spec, "label"),
            requirement=requirement,
            severity=severity,
            scope=_required_str(field_spec, "scope"),
            data_type=_required_str(field_spec, "data_type"),
            canonical_unit=_optional_str(field_spec.get("canonical_unit")),
            allowed_values=_string_tuple(field_spec.get("allowed_values")),
            markets=_string_tuple(field_spec.get("markets")),
            constraints=_mapping(field_spec.get("constraints")),
            mapping=_mapping(field_spec.get("mapping")),
        )

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHTS[self.severity]


def evaluate_product(
    snapshot: ProductAuditSnapshot,
    rules: tuple[TaxonomyFieldRule, ...],
) -> tuple[RuleEvaluation, ...]:
    evaluations: list[RuleEvaluation] = []
    for rule in rules:
        if rule.category_key != snapshot.category_key:
            continue
        targets = _targets(snapshot, rule)
        if not targets:
            evaluations.extend(
                _evaluate_target(
                    snapshot=snapshot,
                    rule=rule,
                    variant_id=None,
                    attribute=None,
                    missing_variant_scope=rule.scope == "variant",
                )
            )
            continue
        for variant_id, attributes in targets:
            evaluations.extend(
                _evaluate_target(
                    snapshot=snapshot,
                    rule=rule,
                    variant_id=variant_id,
                    attribute=attributes.get(rule.field_key),
                    missing_variant_scope=False,
                )
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


def _targets(
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
) -> tuple[tuple[uuid.UUID | None, Mapping[str, AttributeSnapshot]], ...]:
    if rule.scope == "product":
        return ((None, snapshot.attributes),)
    if rule.scope == "variant":
        return tuple((variant.variant_id, variant.attributes) for variant in snapshot.variants)
    if rule.scope == "both":
        return (
            (None, snapshot.attributes),
            *((variant.variant_id, variant.attributes) for variant in snapshot.variants),
        )
    raise RuleSpecificationError(f"unsupported field scope {rule.scope!r}")


def _evaluate_target(
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot | None,
    missing_variant_scope: bool,
) -> tuple[RuleEvaluation, ...]:
    present = (
        attribute is not None
        and attribute.value_state == "present"
        and attribute.value is not None
    )
    presence_codes: tuple[str, ...] = ()
    if not present:
        presence_codes = (
            ("missing_variant_scope",) if missing_variant_scope else ("missing_value",)
        )
    presence = _evaluation(
        snapshot=snapshot,
        rule=rule,
        variant_id=variant_id,
        attribute=attribute,
        check_key="presence",
        dimension="completeness",
        failure_codes=presence_codes,
        business_impact="data_quality",
        remediation_type="supply_source_value",
    )
    evaluations = [presence]
    if not present or attribute is None:
        evaluations.extend(_derived_coverage_evaluations(snapshot, rule, variant_id, presence))
        return tuple(evaluations)

    validation_codes = _validation_failures(attribute, rule)
    validation_dimension: ScoreDimension = (
        "variant_quality" if variant_id is not None else "consistency"
    )
    validation = _evaluation(
        snapshot=snapshot,
        rule=rule,
        variant_id=variant_id,
        attribute=attribute,
        check_key="validation",
        dimension=validation_dimension,
        failure_codes=validation_codes,
        business_impact="data_quality",
        remediation_type=_remediation_type(validation_codes),
    )
    evaluations.append(validation)
    evaluations.extend(_derived_coverage_evaluations(snapshot, rule, variant_id, validation))
    return tuple(evaluations)


def _derived_coverage_evaluations(
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    source: RuleEvaluation,
) -> tuple[RuleEvaluation, ...]:
    evaluations: list[RuleEvaluation] = []
    if _optional_str(rule.mapping.get("seo_role")) or _optional_str(
        rule.mapping.get("schema_org_property")
    ):
        evaluations.append(
            _copy_dimension(
                source,
                snapshot=snapshot,
                rule=rule,
                variant_id=variant_id,
                check_key="discoverability_coverage",
                dimension="discoverability_readiness",
                business_impact="discoverability",
            )
        )
    if rule.markets:
        evaluations.append(
            _copy_dimension(
                source,
                snapshot=snapshot,
                rule=rule,
                variant_id=variant_id,
                check_key="market_coverage",
                dimension="market_consistency",
                business_impact="operations",
            )
        )
    return tuple(evaluations)


def _copy_dimension(
    source: RuleEvaluation,
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    check_key: str,
    dimension: ScoreDimension,
    business_impact: str,
) -> RuleEvaluation:
    failure_codes = source.finding.failure_codes if source.finding else ()
    attribute: AttributeSnapshot | None = None
    if source.finding is not None:
        attribute = AttributeSnapshot(
            key=rule.field_key,
            value=source.finding.affected_value,
            value_type=rule.data_type,
            evidence=source.finding.evidence,
        )
    return _evaluation(
        snapshot=snapshot,
        rule=rule,
        variant_id=variant_id,
        attribute=attribute,
        check_key=check_key,
        dimension=dimension,
        failure_codes=failure_codes,
        business_impact=business_impact,
        remediation_type=(
            source.finding.remediation_type if source.finding else "none"
        ),
    )


def _evaluation(
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot | None,
    check_key: str,
    dimension: ScoreDimension,
    failure_codes: tuple[str, ...],
    business_impact: str,
    remediation_type: str,
) -> RuleEvaluation:
    finding: FindingCandidate | None = None
    outcome: EvaluationOutcome = "passed"
    if failure_codes:
        outcome = "failed"
        finding = _finding(
            snapshot=snapshot,
            rule=rule,
            variant_id=variant_id,
            attribute=attribute,
            check_key=check_key,
            failure_codes=failure_codes,
            business_impact=business_impact,
            remediation_type=remediation_type,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        field_key=rule.field_key,
        check_key=check_key,
        dimension=dimension,
        severity=rule.severity,
        weight=rule.weight,
        outcome=outcome,
        coverage_basis_points=snapshot.source_coverage_basis_points,
        finding=finding,
    )


def _finding(
    *,
    snapshot: ProductAuditSnapshot,
    rule: TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot | None,
    check_key: str,
    failure_codes: tuple[str, ...],
    business_impact: str,
    remediation_type: str,
) -> FindingCandidate:
    codes = tuple(sorted(set(failure_codes)))
    fingerprint = finding_fingerprint(
        rule_version_id=rule.rule_version_id,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        field_key=rule.field_key,
        check_key=check_key,
        failure_codes=codes,
    )
    return FindingCandidate(
        fingerprint=fingerprint,
        rule_version_id=rule.rule_version_id,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        severity=rule.severity,
        title=f"{rule.field_label}: {_failure_title(codes)}",
        explanation=(
            f"{rule.field_label} failed deterministic {check_key} checks: "
            + ", ".join(codes)
        ),
        field_key=rule.field_key,
        affected_value=attribute.value if attribute else None,
        evidence=attribute.evidence if attribute else (),
        business_impact=business_impact,
        remediation_type=remediation_type,
        failure_codes=codes,
    )


def finding_fingerprint(
    *,
    rule_version_id: uuid.UUID,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    field_key: str,
    check_key: str,
    failure_codes: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "rule_version_id": str(rule_version_id),
            "product_id": str(product_id),
            "variant_id": str(variant_id) if variant_id else None,
            "field_key": field_key,
            "check_key": check_key,
            "failure_codes": sorted(set(failure_codes)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validation_failures(
    attribute: AttributeSnapshot,
    rule: TaxonomyFieldRule,
) -> tuple[str, ...]:
    failures: list[str] = []
    value = attribute.value
    if attribute.value_type != rule.data_type:
        failures.append("declared_type_mismatch")
    if not _value_matches_type(value, rule.data_type):
        failures.append("invalid_type")
        return tuple(sorted(set(failures)))
    if rule.canonical_unit and attribute.unit != rule.canonical_unit:
        failures.append("invalid_unit")
    minimum = _optional_number(rule.constraints.get("minimum"))
    maximum = _optional_number(rule.constraints.get("maximum"))
    numeric = _optional_number(value)
    if minimum is not None and numeric is not None and numeric < minimum:
        failures.append("below_minimum")
    if maximum is not None and numeric is not None and numeric > maximum:
        failures.append("above_maximum")
    min_length = _optional_int(rule.constraints.get("min_length"))
    max_length = _optional_int(rule.constraints.get("max_length"))
    length = _value_length(value)
    if min_length is not None and length is not None and length < min_length:
        failures.append("below_min_length")
    if max_length is not None and length is not None and length > max_length:
        failures.append("above_max_length")
    pattern = _optional_str(rule.constraints.get("pattern"))
    if pattern and isinstance(value, str) and re.fullmatch(pattern, value) is None:
        failures.append("pattern_mismatch")
    if rule.allowed_values:
        values = value if isinstance(value, list | tuple) else [value]
        if any(
            not isinstance(item, str) or item not in rule.allowed_values
            for item in values
        ):
            failures.append("value_not_allowed")
    if rule.data_type == "url" and isinstance(value, str) and not _valid_url(value):
        failures.append("invalid_url")
    if rule.data_type == "date" and isinstance(value, str) and not _valid_date(value):
        failures.append("invalid_date")
    return tuple(sorted(set(failures)))


def _value_matches_type(value: AttributeValue, data_type: str) -> bool:
    if data_type in {"string", "url", "date", "enum"}:
        return isinstance(value, str)
    if data_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type == "decimal":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type == "list":
        return isinstance(value, list | tuple)
    raise RuleSpecificationError(f"unsupported data type {data_type!r}")


def _valid_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and parsed.hostname is not None
    except ValueError:
        return False


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _value_length(value: AttributeValue) -> int | None:
    if isinstance(value, str | list | tuple):
        return len(value)
    return None


def _failure_title(codes: tuple[str, ...]) -> str:
    if "missing_value" in codes or "missing_variant_scope" in codes:
        return "missing expected data"
    return "invalid canonical value"


def _remediation_type(codes: tuple[str, ...]) -> str:
    if not codes:
        return "none"
    if "invalid_unit" in codes:
        return "normalize_unit"
    if "invalid_type" in codes:
        return "correct_type"
    if "value_not_allowed" in codes:
        return "choose_allowed_value"
    return "correct_value"


def _severity(value: str) -> Severity:
    if value not in SEVERITY_WEIGHTS:
        raise RuleSpecificationError(f"unsupported severity {value!r}")
    return cast(Severity, value)


def _required_str(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuleSpecificationError(f"{key!r} must be a non-empty string")
    return value


def _required_mapping(mapping: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise RuleSpecificationError(f"{key!r} must be an object")
    return cast(Mapping[str, object], value)


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _optional_number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
