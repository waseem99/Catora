from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from catora_api.auditing import _duplicate_base_rules as _rule_types
from catora_api.auditing.types import (
    AttributeValue,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
)

DUPLICATE_CONTENT_ALGORITHM_VERSION = "duplicate-content-v1"
_DUPLICATE_FAILURE_CODES = frozenset(
    {
        "title_exact_duplicate",
        "title_near_duplicate",
        "description_exact_duplicate",
        "description_near_duplicate",
    }
)


class DuplicateContentRuleConfigurationError(ValueError):
    pass


def is_duplicate_content_rule(rule: _rule_types.TaxonomyFieldRule) -> bool:
    value: object = rule.constraints.get("duplicate_content_kind")
    return isinstance(value, str) and value == "catalog_similarity"


def evaluate_duplicate_content_rule(
    snapshot: ProductAuditSnapshot,
    rule: _rule_types.TaxonomyFieldRule,
) -> RuleEvaluation:
    if not is_duplicate_content_rule(rule):
        raise DuplicateContentRuleConfigurationError(
            f"Rule {rule.rule_key!r} is not a duplicate-content rule"
        )
    attribute = snapshot.attributes.get(rule.field_key)
    if attribute is None or attribute.value_state != "present":
        return _not_evaluated(snapshot, rule)
    payload = _payload(attribute.value)
    failure_codes = _failure_codes(payload.get("failure_codes"))
    finding: FindingCandidate | None = None
    if failure_codes:
        finding = FindingCandidate(
            fingerprint=_rule_types.finding_fingerprint(
                rule_version_id=rule.rule_version_id,
                product_id=snapshot.product_id,
                variant_id=None,
                field_key=rule.field_key,
                check_key="duplicate_content",
                failure_codes=failure_codes,
            ),
            rule_version_id=rule.rule_version_id,
            product_id=snapshot.product_id,
            variant_id=None,
            severity=rule.severity,
            title="Duplicate content: differentiate catalog copy",
            explanation=(
                "Catalog title or description matched another product under the "
                "deterministic duplicate-content algorithm: "
                + ", ".join(failure_codes)
            ),
            field_key=rule.field_key,
            affected_value=cast(AttributeValue, dict(payload)),
            evidence=attribute.evidence,
            business_impact="discoverability",
            remediation_type="differentiate_product_content",
            failure_codes=failure_codes,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=None,
        field_key=rule.field_key,
        check_key="duplicate_content",
        dimension="discoverability_readiness",
        severity=rule.severity,
        weight=rule.weight,
        outcome="failed" if failure_codes else "passed",
        coverage_basis_points=(
            10000 if attribute.evidence else snapshot.source_coverage_basis_points
        ),
        finding=finding,
    )


def _not_evaluated(
    snapshot: ProductAuditSnapshot,
    rule: _rule_types.TaxonomyFieldRule,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=None,
        field_key=rule.field_key,
        check_key="duplicate_content",
        dimension="discoverability_readiness",
        severity=rule.severity,
        weight=rule.weight,
        outcome="not_evaluated",
        coverage_basis_points=snapshot.source_coverage_basis_points,
    )


def _payload(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DuplicateContentRuleConfigurationError(
            "Duplicate-content snapshot payload must be an object"
        )
    return cast(Mapping[str, object], value)


def _failure_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise DuplicateContentRuleConfigurationError(
            "Duplicate-content failure_codes must be a list"
        )
    codes = tuple(sorted({item for item in value if isinstance(item, str)}))
    unsupported = set(codes) - _DUPLICATE_FAILURE_CODES
    if unsupported:
        raise DuplicateContentRuleConfigurationError(
            f"Unsupported duplicate-content failure codes: {sorted(unsupported)!r}"
        )
    return codes
