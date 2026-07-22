from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import cast

from catora_api.auditing import _relational_rules as _base
from catora_api.auditing.types import (
    AttributeSnapshot,
    AttributeValue,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
)

IMAGE_QUALITY_ALGORITHM_VERSION = "image-quality-v1"
_WHITESPACE_PATTERN = re.compile(r"\s+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_GENERIC_ALT_TOKENS = frozenset(
    {"image", "photo", "picture", "product", "item", "furniture"}
)


class ImageRuleConfigurationError(ValueError):
    pass


def is_image_quality_rule(rule: _base.TaxonomyFieldRule) -> bool:
    return rule.constraints.get("image_quality_kind") == "inventory_alt_text"


def evaluate_image_quality_rule(
    snapshot: ProductAuditSnapshot,
    rule: _base.TaxonomyFieldRule,
) -> RuleEvaluation:
    if not is_image_quality_rule(rule):
        raise ImageRuleConfigurationError(
            f"Rule {rule.rule_key!r} is not an image-quality rule"
        )
    attribute = snapshot.attributes.get(rule.field_key)
    images = _present_images(attribute)
    title = _present_string(snapshot.attributes.get("title")) or ""
    failure_codes = _image_failures(
        images,
        title=title,
        constraints=rule.constraints,
    )
    affected_value = list(images) if images is not None else []
    evidence = attribute.evidence if attribute is not None else ()
    finding: FindingCandidate | None = None
    if failure_codes:
        finding = FindingCandidate(
            fingerprint=_base.finding_fingerprint(
                rule_version_id=rule.rule_version_id,
                product_id=snapshot.product_id,
                variant_id=None,
                field_key=rule.field_key,
                check_key="image_quality",
                failure_codes=failure_codes,
            ),
            rule_version_id=rule.rule_version_id,
            product_id=snapshot.product_id,
            variant_id=None,
            severity=rule.severity,
            title="Image quality: improve image coverage and alt text",
            explanation=(
                f"{rule.field_label} failed deterministic image checks: "
                + ", ".join(failure_codes)
            ),
            field_key=rule.field_key,
            affected_value=cast(AttributeValue, affected_value),
            evidence=evidence,
            business_impact="discoverability",
            remediation_type="improve_image_metadata",
            failure_codes=failure_codes,
        )
    return RuleEvaluation(
        rule_version_id=rule.rule_version_id,
        rule_key=rule.rule_key,
        product_id=snapshot.product_id,
        variant_id=None,
        field_key=rule.field_key,
        check_key="image_quality",
        dimension="discoverability_readiness",
        severity=rule.severity,
        weight=rule.weight,
        outcome="failed" if failure_codes else "passed",
        coverage_basis_points=(
            10000 if evidence else snapshot.source_coverage_basis_points
        ),
        finding=finding,
    )


def _image_failures(
    images: tuple[Mapping[str, object], ...] | None,
    *,
    title: str,
    constraints: Mapping[str, object],
) -> tuple[str, ...]:
    minimum_count = _required_positive_int(constraints, "min_image_count")
    if not images:
        return ("image_missing",)
    failures: list[str] = []
    if len(images) < minimum_count:
        failures.append("image_count_below_minimum")
    require_alt_text = _required_bool(constraints, "require_alt_text")
    minimum_alt_length = _required_positive_int(constraints, "min_alt_length")
    maximum_alt_length = _required_positive_int(constraints, "max_alt_length")
    normalized_title = _normalize_text(title)
    identities: list[str] = []
    for image in images:
        checksum = _optional_string(image.get("checksum"))
        url = _optional_string(image.get("url"))
        if checksum or url:
            identities.append(checksum or url or "")
        alt_text = _normalize_text(_optional_string(image.get("alt_text")))
        if require_alt_text and not alt_text:
            failures.append("image_alt_missing")
            continue
        if not alt_text:
            continue
        if len(alt_text) < minimum_alt_length:
            failures.append("image_alt_too_short")
        if len(alt_text) > maximum_alt_length:
            failures.append("image_alt_too_long")
        alt_tokens = _tokens(alt_text)
        if alt_tokens and set(alt_tokens) <= _GENERIC_ALT_TOKENS:
            failures.append("image_alt_generic")
        if normalized_title and alt_text.casefold() == normalized_title.casefold():
            failures.append("image_alt_duplicates_title")
    if identities and max(Counter(identities).values()) > 1:
        failures.append("image_duplicate")
    return tuple(sorted(set(failures)))


def _present_string(attribute: AttributeSnapshot | None) -> str | None:
    if (
        attribute is None
        or attribute.value_state != "present"
        or not isinstance(attribute.value, str)
    ):
        return None
    return attribute.value


def _present_images(
    attribute: AttributeSnapshot | None,
) -> tuple[Mapping[str, object], ...] | None:
    if (
        attribute is None
        or attribute.value_state != "present"
        or not isinstance(attribute.value, Sequence)
        or isinstance(attribute.value, str | bytes | bytearray)
    ):
        return None
    return tuple(
        cast(Mapping[str, object], value)
        for value in attribute.value
        if isinstance(value, Mapping)
    )


def _normalize_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_PATTERN.sub(
        " ",
        unicodedata.normalize("NFKC", value),
    ).strip()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(value.casefold()))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_bool(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise ImageRuleConfigurationError(f"{key!r} must be a boolean")
    return value


def _required_positive_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ImageRuleConfigurationError(f"{key!r} must be a positive integer")
    return value
