from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from catora_api.auditing import _relational_rules as _base
from catora_api.auditing.types import (
    AttributeSnapshot,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
    Severity,
)

CONTENT_QUALITY_ALGORITHM_VERSION = "content-quality-v1"
type ContentRuleKind = Literal["title_quality", "description_quality"]
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_GENERIC_TITLE_TOKENS = frozenset(
    {"item", "new", "product", "products", "furniture", "home", "untitled"}
)


class ContentRuleConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContentRuleTemplate:
    suffix: str
    label: str
    kind: ContentRuleKind
    field_key: str
    severity: Severity
    constraints: Mapping[str, object]


CONTENT_RULE_TEMPLATES: tuple[ContentRuleTemplate, ...] = (
    ContentRuleTemplate(
        suffix="title_quality",
        label="title quality",
        kind="title_quality",
        field_key="title",
        severity="medium",
        constraints={
            "content_quality_kind": "title_quality",
            "min_length": 8,
            "max_length": 180,
            "max_repeated_token_count": 2,
        },
    ),
    ContentRuleTemplate(
        suffix="description_quality",
        label="description quality",
        kind="description_quality",
        field_key="description",
        severity="medium",
        constraints={
            "content_quality_kind": "description_quality",
            "min_length": 60,
            "max_length": 5000,
            "min_unique_token_ratio_basis_points": 3000,
        },
    ),
)


def is_content_quality_rule(rule: _base.TaxonomyFieldRule) -> bool:
    return _content_kind(rule) is not None


def evaluate_content_quality_rule(
    snapshot: ProductAuditSnapshot,
    rule: _base.TaxonomyFieldRule,
) -> RuleEvaluation:
    kind = _content_kind(rule)
    if kind is None:
        raise ContentRuleConfigurationError(
            f"Rule {rule.rule_key!r} is not a content-quality rule"
        )
    attribute = snapshot.attributes.get(rule.field_key)
    value = _present_string(attribute)
    evidence = attribute.evidence if attribute is not None else ()
    if kind == "title_quality":
        failure_codes = _title_failures(value, rule.constraints)
        business_impact = "discoverability"
        remediation_type = "rewrite_title"
        finding_title = "Title quality: improve catalog title"
    else:
        title_attribute = snapshot.attributes.get("title")
        title_value = _present_string(title_attribute) or ""
        failure_codes = _description_failures(
            value,
            title=title_value,
            constraints=rule.constraints,
        )
        business_impact = "conversion"
        remediation_type = "rewrite_description"
        finding_title = "Description quality: improve product copy"

    finding: FindingCandidate | None = None
    if failure_codes:
        finding = FindingCandidate(
            fingerprint=_base.finding_fingerprint(
                rule_version_id=rule.rule_version_id,
                product_id=snapshot.product_id,
                variant_id=None,
                field_key=rule.field_key,
                check_key=kind,
                failure_codes=failure_codes,
            ),
            rule_version_id=rule.rule_version_id,
            product_id=snapshot.product_id,
            variant_id=None,
            severity=rule.severity,
            title=finding_title,
            explanation=(
                f"{rule.field_label} failed deterministic quality checks: "
                + ", ".join(failure_codes)
            ),
            field_key=rule.field_key,
            affected_value=value,
            evidence=evidence,
            business_impact=business_impact,
            remediation_type=remediation_type,
            failure_codes=failure_codes,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=None,
        field_key=rule.field_key,
        check_key=kind,
        dimension="discoverability_readiness",
        severity=rule.severity,
        weight=rule.weight,
        outcome="failed" if failure_codes else "passed",
        coverage_basis_points=(
            10000 if evidence else snapshot.source_coverage_basis_points
        ),
        finding=finding,
    )


def _content_kind(rule: _base.TaxonomyFieldRule) -> ContentRuleKind | None:
    value = rule.constraints.get("content_quality_kind")
    if value in {"title_quality", "description_quality"}:
        return cast(ContentRuleKind, value)
    return None


def _title_failures(
    value: str | None,
    constraints: Mapping[str, object],
) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    if not normalized:
        return ("title_missing",)
    failures: list[str] = []
    minimum = _required_positive_int(constraints, "min_length")
    maximum = _required_positive_int(constraints, "max_length")
    if len(normalized) < minimum:
        failures.append("title_too_short")
    if len(normalized) > maximum:
        failures.append("title_too_long")
    tokens = _tokens(normalized)
    if tokens and set(tokens) <= _GENERIC_TITLE_TOKENS:
        failures.append("title_generic")
    if _is_all_caps(normalized):
        failures.append("title_all_caps")
    max_repeated = _required_positive_int(constraints, "max_repeated_token_count")
    if tokens and max(Counter(tokens).values()) > max_repeated:
        failures.append("title_repeated_terms")
    return tuple(sorted(set(failures)))


def _description_failures(
    value: str | None,
    *,
    title: str,
    constraints: Mapping[str, object],
) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    if not normalized:
        return ("description_missing",)
    failures: list[str] = []
    minimum = _required_positive_int(constraints, "min_length")
    maximum = _required_positive_int(constraints, "max_length")
    if len(normalized) < minimum:
        failures.append("description_too_short")
    if len(normalized) > maximum:
        failures.append("description_too_long")
    tokens = _tokens(normalized)
    minimum_ratio = _required_basis_points(
        constraints,
        "min_unique_token_ratio_basis_points",
    )
    if tokens and (len(set(tokens)) * 10000) // len(tokens) < minimum_ratio:
        failures.append("description_low_variety")
    normalized_title = _normalize_text(title)
    if normalized_title and normalized.casefold() == normalized_title.casefold():
        failures.append("description_duplicates_title")
    return tuple(sorted(set(failures)))


def _present_string(attribute: AttributeSnapshot | None) -> str | None:
    if (
        attribute is None
        or attribute.value_state != "present"
        or not isinstance(attribute.value, str)
    ):
        return None
    return attribute.value


def _normalize_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_PATTERN.sub(
        " ",
        unicodedata.normalize("NFKC", value),
    ).strip()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(value.casefold()))


def _is_all_caps(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    return len(letters) >= 4 and value == value.upper() and value != value.lower()


def _required_positive_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContentRuleConfigurationError(f"{key!r} must be a positive integer")
    return value


def _required_basis_points(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000:
        raise ContentRuleConfigurationError(f"{key!r} must be between 0 and 10000")
    return value


def content_rule_keys(
    categories: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        f"builtin.{category_key}.{template.suffix}"
        for category_key in sorted(categories)
        for template in CONTENT_RULE_TEMPLATES
    )
