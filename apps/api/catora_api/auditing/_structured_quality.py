from __future__ import annotations

import re
import uuid
from collections.abc import Mapping

from catora_api.auditing import _relational_rules as _base
from catora_api.auditing.types import (
    AttributeSnapshot,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
)

STRUCTURED_DATA_ALGORITHM_VERSION = "structured-data-coverage-v1"
_PATH_NORMALIZER = re.compile(r"[^a-z0-9]+")


class StructuredDataRuleConfigurationError(ValueError):
    pass


def is_structured_data_rule(rule: _base.TaxonomyFieldRule) -> bool:
    return rule.constraints.get("structured_data_quality_kind") == "evidence_coverage"


def evaluate_structured_data_rule(
    snapshot: ProductAuditSnapshot,
    rule: _base.TaxonomyFieldRule,
) -> tuple[RuleEvaluation, ...]:
    if not is_structured_data_rule(rule):
        raise StructuredDataRuleConfigurationError(
            f"Rule {rule.rule_key!r} is not a structured-data rule"
        )
    targets = _targets(snapshot, rule)
    if not targets:
        return (
            _evaluation(
                snapshot=snapshot,
                rule=rule,
                variant_id=None,
                attribute=None,
            ),
        )
    return tuple(
        _evaluation(
            snapshot=snapshot,
            rule=rule,
            variant_id=variant_id,
            attribute=attributes.get(rule.field_key),
        )
        for variant_id, attributes in targets
    )


def _targets(
    snapshot: ProductAuditSnapshot,
    rule: _base.TaxonomyFieldRule,
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
            *((variant.variant_id, variant.attributes) for variant in snapshot.variants),
        )
    raise StructuredDataRuleConfigurationError(
        f"Unsupported structured-data field scope {rule.scope!r}"
    )


def _evaluation(
    *,
    snapshot: ProductAuditSnapshot,
    rule: _base.TaxonomyFieldRule,
    variant_id: uuid.UUID | None,
    attribute: AttributeSnapshot | None,
) -> RuleEvaluation:
    present = (
        attribute is not None
        and attribute.value_state == "present"
        and attribute.value is not None
    )
    evidence = attribute.evidence if attribute is not None else ()
    if not present:
        return RuleEvaluation(
            rule_version_id=rule.rule_version_id,
            rule_key=rule.rule_key,
            product_id=snapshot.product_id,
            variant_id=variant_id,
            field_key=rule.field_key,
            check_key="structured_data_coverage",
            dimension="discoverability_readiness",
            severity=rule.severity,
            weight=rule.weight,
            outcome="not_evaluated",
            coverage_basis_points=snapshot.source_coverage_basis_points,
        )

    accepted_tokens = _string_tuple(rule.constraints.get("accepted_path_tokens"))
    if not accepted_tokens:
        raise StructuredDataRuleConfigurationError(
            "Structured-data rule requires accepted_path_tokens"
        )
    covered = any(_path_matches(item.field_path, accepted_tokens) for item in evidence)
    failure_codes: tuple[str, ...] = () if covered else (
        "structured_data_evidence_missing",
    )
    finding: FindingCandidate | None = None
    if failure_codes:
        schema_property = rule.constraints.get("schema_org_property")
        finding = FindingCandidate(
            fingerprint=_base.finding_fingerprint(
                rule_version_id=rule.rule_version_id,
                product_id=snapshot.product_id,
                variant_id=variant_id,
                field_key=rule.field_key,
                check_key="structured_data_coverage",
                failure_codes=failure_codes,
            ),
            rule_version_id=rule.rule_version_id,
            product_id=snapshot.product_id,
            variant_id=variant_id,
            severity=rule.severity,
            title=f"{rule.field_label}: add structured-data coverage",
            explanation=(
                f"No accepted structured-data evidence path covers "
                f"Schema.org property {schema_property!r}."
            ),
            field_key=rule.field_key,
            affected_value=attribute.value if attribute is not None else None,
            evidence=evidence,
            business_impact="discoverability",
            remediation_type="add_structured_data_mapping",
            failure_codes=failure_codes,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=variant_id,
        field_key=rule.field_key,
        check_key="structured_data_coverage",
        dimension="discoverability_readiness",
        severity=rule.severity,
        weight=rule.weight,
        outcome="failed" if failure_codes else "passed",
        coverage_basis_points=(
            10000 if evidence else snapshot.source_coverage_basis_points
        ),
        finding=finding,
    )


def _path_matches(field_path: str, accepted_tokens: tuple[str, ...]) -> bool:
    normalized = _PATH_NORMALIZER.sub("_", field_path.casefold()).strip("_")
    framed = f"_{normalized}_"
    return any(
        f"_{_PATH_NORMALIZER.sub('_', token.casefold()).strip('_')}_" in framed
        for token in accepted_tokens
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
