from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

from catora_api.auditing.rules import (
    SEVERITY_WEIGHTS,
    TaxonomyFieldRule,
    evaluate_catalog,
    finding_fingerprint,
)
from catora_api.auditing.types import (
    AttributeSnapshot,
    AttributeValue,
    EvidenceSnapshot,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
    ScoreDimension,
    Severity,
)

RESTAURANT_AUDIT_PACK_VERSION = "restaurant-web-audit/v1"
_RESTAURANT_RULE_NAMESPACE = uuid.UUID("bf1df0a7-e721-49f3-a40a-50ead574887c")

RestaurantPageType = Literal["brand", "location", "service_area", "menu", "menu_item"]
RestaurantPageCategory = Literal[
    "restaurant.web.brand",
    "restaurant.web.location",
    "restaurant.web.service_area",
    "restaurant.web.menu",
    "restaurant.web.menu_item",
]

_PAGE_CATEGORY: dict[RestaurantPageType, RestaurantPageCategory] = {
    "brand": "restaurant.web.brand",
    "location": "restaurant.web.location",
    "service_area": "restaurant.web.service_area",
    "menu": "restaurant.web.menu",
    "menu_item": "restaurant.web.menu_item",
}

_REQUIRED_SCHEMA_TYPES: dict[RestaurantPageType, frozenset[str]] = {
    "brand": frozenset({"Organization"}),
    "location": frozenset({"Restaurant"}),
    "service_area": frozenset({"Restaurant"}),
    "menu": frozenset({"Menu"}),
    "menu_item": frozenset({"MenuItem"}),
}


@dataclass(frozen=True, slots=True)
class RestaurantWebPageSnapshot:
    page_id: uuid.UUID
    page_type: RestaurantPageType
    url: str
    status_code: int
    indexable: bool
    robots_allowed: bool
    sitemap_listed: bool
    canonical_url: str | None
    title: str | None
    meta_description: str | None
    h1: str | None
    body_text: str
    rendered_text: str | None
    structured_data_types: tuple[str, ...]
    internal_link_count: int
    response_time_ms: int | None
    observed_at: datetime
    volatile_fact_observed_at: datetime | None = None
    evidence: tuple[EvidenceSnapshot, ...] = ()
    source_coverage_basis_points: int = 10_000

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.volatile_fact_observed_at is not None:
            if self.volatile_fact_observed_at.tzinfo is None:
                raise ValueError("volatile_fact_observed_at must be timezone-aware")
            if self.volatile_fact_observed_at > self.observed_at:
                raise ValueError("volatile fact observation cannot be in the future")
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("status_code must be an HTTP status")
        if self.internal_link_count < 0:
            raise ValueError("internal_link_count cannot be negative")
        if self.response_time_ms is not None and self.response_time_ms < 0:
            raise ValueError("response_time_ms cannot be negative")
        if not 0 <= self.source_coverage_basis_points <= 10_000:
            raise ValueError("source coverage must be between 0 and 10000")


@dataclass(frozen=True, slots=True)
class RestaurantAuditPack:
    version: str
    rules: tuple[TaxonomyFieldRule, ...]


def restaurant_audit_pack() -> RestaurantAuditPack:
    rules: list[TaxonomyFieldRule] = []
    for category in _PAGE_CATEGORY.values():
        rules.extend(
            (
                _field_rule(
                    category=category,
                    field_key="url",
                    label="Page URL",
                    requirement="required",
                    severity="critical",
                    data_type="url",
                    constraints={},
                    mapping={"seo_role": "page_url"},
                ),
                _field_rule(
                    category=category,
                    field_key="status_code",
                    label="HTTP status",
                    requirement="required",
                    severity="critical",
                    data_type="integer",
                    constraints={"minimum": 200, "maximum": 399},
                    mapping={"seo_role": "crawlability"},
                ),
                _field_rule(
                    category=category,
                    field_key="canonical_url",
                    label="Canonical URL",
                    requirement="required",
                    severity="high",
                    data_type="url",
                    constraints={},
                    mapping={"seo_role": "canonical"},
                ),
                _field_rule(
                    category=category,
                    field_key="title",
                    label="Page title",
                    requirement="required",
                    severity="high",
                    data_type="string",
                    constraints={"min_length": 20, "max_length": 65},
                    mapping={"seo_role": "title"},
                ),
                _field_rule(
                    category=category,
                    field_key="meta_description",
                    label="Meta description",
                    requirement="recommended",
                    severity="medium",
                    data_type="string",
                    constraints={"min_length": 70, "max_length": 170},
                    mapping={"seo_role": "description"},
                ),
                _field_rule(
                    category=category,
                    field_key="h1",
                    label="Primary heading",
                    requirement="required",
                    severity="high",
                    data_type="string",
                    constraints={"min_length": 3, "max_length": 150},
                    mapping={"seo_role": "heading"},
                ),
                _field_rule(
                    category=category,
                    field_key="body_text",
                    label="Visible body content",
                    requirement="required",
                    severity="high",
                    data_type="string",
                    constraints={"min_length": 200},
                    mapping={"seo_role": "content"},
                ),
                _field_rule(
                    category=category,
                    field_key="structured_data_types",
                    label="Structured data",
                    requirement="recommended",
                    severity="medium",
                    data_type="list",
                    constraints={"min_length": 1},
                    mapping={"schema_org_property": "@type"},
                ),
                _field_rule(
                    category=category,
                    field_key="internal_link_count",
                    label="Internal links",
                    requirement="recommended",
                    severity="medium",
                    data_type="integer",
                    constraints={"minimum": 1},
                    mapping={"seo_role": "internal_links"},
                ),
                _field_rule(
                    category=category,
                    field_key="response_time_ms",
                    label="Response time",
                    requirement="recommended",
                    severity="medium",
                    data_type="integer",
                    constraints={"maximum": 5_000},
                    mapping={"seo_role": "performance"},
                ),
            )
        )
    return RestaurantAuditPack(version=RESTAURANT_AUDIT_PACK_VERSION, rules=tuple(rules))


def restaurant_page_snapshot(page: RestaurantWebPageSnapshot) -> ProductAuditSnapshot:
    attributes: dict[str, AttributeSnapshot] = {
        "url": _attribute("url", page.url, "url", page.evidence),
        "status_code": _attribute("status_code", page.status_code, "integer", page.evidence),
        "indexable": _attribute("indexable", page.indexable, "boolean", page.evidence),
        "robots_allowed": _attribute(
            "robots_allowed", page.robots_allowed, "boolean", page.evidence
        ),
        "sitemap_listed": _attribute(
            "sitemap_listed", page.sitemap_listed, "boolean", page.evidence
        ),
        "body_text": _attribute("body_text", page.body_text, "string", page.evidence),
        "structured_data_types": _attribute(
            "structured_data_types",
            list(page.structured_data_types),
            "list",
            page.evidence,
        ),
        "internal_link_count": _attribute(
            "internal_link_count", page.internal_link_count, "integer", page.evidence
        ),
    }
    for key, value, value_type in (
        ("canonical_url", page.canonical_url, "url"),
        ("title", page.title, "string"),
        ("meta_description", page.meta_description, "string"),
        ("h1", page.h1, "string"),
        ("rendered_text", page.rendered_text, "string"),
        ("response_time_ms", page.response_time_ms, "integer"),
    ):
        attributes[key] = _attribute(
            key,
            cast(AttributeValue, value),
            value_type,
            page.evidence,
        )
    return ProductAuditSnapshot(
        product_id=page.page_id,
        category_key=_PAGE_CATEGORY[page.page_type],
        attributes=attributes,
        source_coverage_basis_points=page.source_coverage_basis_points,
    )


def evaluate_restaurant_pages(
    pages: tuple[RestaurantWebPageSnapshot, ...],
    *,
    as_of: datetime | None = None,
) -> tuple[RuleEvaluation, ...]:
    current_time = as_of or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    pack = restaurant_audit_pack()
    base = list(
        evaluate_catalog(
            tuple(restaurant_page_snapshot(page) for page in pages),
            pack.rules,
        )
    )
    for page in pages:
        base.extend(_specialized_evaluations(page, as_of=current_time))
    return tuple(
        sorted(
            base,
            key=lambda evaluation: (
                str(evaluation.product_id),
                evaluation.rule_key,
                evaluation.check_key,
                evaluation.field_key,
            ),
        )
    )


def _field_rule(
    *,
    category: RestaurantPageCategory,
    field_key: str,
    label: str,
    requirement: Literal["required", "recommended"],
    severity: Severity,
    data_type: str,
    constraints: dict[str, object],
    mapping: dict[str, object],
) -> TaxonomyFieldRule:
    rule_key = f"builtin.{category}.{field_key}.restaurant_web_quality"
    return TaxonomyFieldRule(
        rule_version_id=uuid.uuid5(
            _RESTAURANT_RULE_NAMESPACE,
            f"{RESTAURANT_AUDIT_PACK_VERSION}:{rule_key}",
        ),
        rule_key=rule_key,
        rule_version=RESTAURANT_AUDIT_PACK_VERSION,
        category_key=category,
        field_key=field_key,
        field_label=label,
        requirement=requirement,
        severity=severity,
        scope="product",
        data_type=data_type,
        canonical_unit=None,
        allowed_values=(),
        markets=(),
        constraints=constraints,
        mapping=mapping,
    )


def _attribute(
    key: str,
    value: AttributeValue,
    value_type: str,
    evidence: tuple[EvidenceSnapshot, ...],
) -> AttributeSnapshot:
    return AttributeSnapshot(
        key=key,
        value=value,
        value_type=value_type,
        value_state="present" if value is not None else "missing",
        evidence=evidence,
    )


def _specialized_evaluations(
    page: RestaurantWebPageSnapshot,
    *,
    as_of: datetime,
) -> tuple[RuleEvaluation, ...]:
    evaluations: list[RuleEvaluation] = []
    evaluations.append(
        _boolean_expectation(
            page,
            field_key="indexable",
            actual=page.indexable,
            severity="critical",
            failure_code="page_not_indexable",
            remediation_type="restore_indexability",
        )
    )
    evaluations.append(
        _boolean_expectation(
            page,
            field_key="robots_allowed",
            actual=page.robots_allowed,
            severity="critical",
            failure_code="robots_blocked",
            remediation_type="allow_authorized_crawling",
        )
    )
    evaluations.append(
        _boolean_expectation(
            page,
            field_key="sitemap_listed",
            actual=page.sitemap_listed,
            severity="high",
            failure_code="missing_from_sitemap",
            remediation_type="add_to_sitemap",
        )
    )
    canonical_matches = (
        page.canonical_url is not None
        and _normalized_url(page.canonical_url) == _normalized_url(page.url)
    )
    evaluations.append(
        _condition_evaluation(
            page,
            rule_suffix="canonical_consistency",
            field_key="canonical_url",
            check_key="canonical_consistency",
            passed=canonical_matches,
            severity="high",
            dimension="consistency",
            failure_code="canonical_target_mismatch",
            business_impact="discoverability",
            remediation_type="correct_canonical_target",
            affected_value=page.canonical_url,
        )
    )
    required_schema = _REQUIRED_SCHEMA_TYPES[page.page_type]
    actual_schema = set(page.structured_data_types)
    evaluations.append(
        _condition_evaluation(
            page,
            rule_suffix="schema_type_consistency",
            field_key="structured_data_types",
            check_key="schema_type_consistency",
            passed=required_schema.issubset(actual_schema),
            severity="high",
            dimension="discoverability_readiness",
            failure_code="required_restaurant_schema_missing",
            business_impact="discoverability",
            remediation_type="add_supported_restaurant_schema",
            affected_value=sorted(actual_schema),
        )
    )
    raw_words = _word_count(page.body_text)
    rendered_words = _word_count(page.rendered_text or "")
    rendered_consistent = (
        page.rendered_text is None
        or raw_words < 50
        or rendered_words >= raw_words // 3
    )
    evaluations.append(
        _condition_evaluation(
            page,
            rule_suffix="rendered_content_consistency",
            field_key="rendered_text",
            check_key="rendered_content_consistency",
            passed=rendered_consistent,
            severity="high",
            dimension="consistency",
            failure_code="content_hidden_after_render",
            business_impact="discoverability",
            remediation_type="expose_content_in_rendered_html",
            affected_value=f"raw_words={raw_words};rendered_words={rendered_words}",
        )
    )
    thin_threshold = 150 if page.page_type in {"location", "service_area"} else 100
    evaluations.append(
        _condition_evaluation(
            page,
            rule_suffix="content_depth",
            field_key="body_text",
            check_key="content_depth",
            passed=raw_words >= thin_threshold,
            severity="medium",
            dimension="discoverability_readiness",
            failure_code="thin_restaurant_page",
            business_impact="discoverability",
            remediation_type="add_unique_evidence_backed_content",
            affected_value=raw_words,
        )
    )
    if page.volatile_fact_observed_at is not None:
        age_days = (as_of - page.volatile_fact_observed_at).total_seconds() // 86_400
        freshness_limit = 7 if page.page_type in {"menu", "menu_item"} else 30
        evaluations.append(
            _condition_evaluation(
                page,
                rule_suffix="volatile_fact_freshness",
                field_key="volatile_fact_observed_at",
                check_key="freshness",
                passed=age_days <= freshness_limit,
                severity="high",
                dimension="consistency",
                failure_code="volatile_restaurant_fact_stale",
                business_impact="operations",
                remediation_type="refresh_volatile_restaurant_facts",
                affected_value=int(age_days),
            )
        )
    blocked = page.status_code in {401, 403, 429, 503} and bool(
        re.search(
            r"captcha|access denied|forbidden|cloudflare|bot verification",
            page.body_text,
            flags=re.IGNORECASE,
        )
    )
    evaluations.append(
        _condition_evaluation(
            page,
            rule_suffix="access_diagnostics",
            field_key="status_code",
            check_key="access_diagnostics",
            passed=not blocked,
            severity="critical",
            dimension="discoverability_readiness",
            failure_code="bot_or_waf_access_blocked",
            business_impact="discoverability",
            remediation_type="review_waf_bot_access_policy",
            affected_value=page.status_code,
        )
    )
    return tuple(evaluations)


def _boolean_expectation(
    page: RestaurantWebPageSnapshot,
    *,
    field_key: str,
    actual: bool,
    severity: Severity,
    failure_code: str,
    remediation_type: str,
) -> RuleEvaluation:
    return _condition_evaluation(
        page,
        rule_suffix=field_key,
        field_key=field_key,
        check_key="expected_true",
        passed=actual,
        severity=severity,
        dimension="discoverability_readiness",
        failure_code=failure_code,
        business_impact="discoverability",
        remediation_type=remediation_type,
        affected_value=actual,
    )


def _condition_evaluation(
    page: RestaurantWebPageSnapshot,
    *,
    rule_suffix: str,
    field_key: str,
    check_key: str,
    passed: bool,
    severity: Severity,
    dimension: ScoreDimension,
    failure_code: str,
    business_impact: str,
    remediation_type: str,
    affected_value: AttributeValue,
) -> RuleEvaluation:
    rule_key = f"builtin.restaurant.{rule_suffix}.{RESTAURANT_AUDIT_PACK_VERSION}"
    rule_version_id = uuid.uuid5(_RESTAURANT_RULE_NAMESPACE, rule_key)
    finding = None
    if not passed:
        fingerprint = finding_fingerprint(
            rule_version_id=rule_version_id,
            product_id=page.page_id,
            variant_id=None,
            field_key=field_key,
            check_key=check_key,
            failure_codes=(failure_code,),
        )
        finding = FindingCandidate(
            fingerprint=fingerprint,
            rule_version_id=rule_version_id,
            product_id=page.page_id,
            variant_id=None,
            severity=severity,
            title=f"Restaurant page: {failure_code.replace('_', ' ')}",
            explanation=(
                f"Restaurant page {page.url} failed deterministic {check_key}: "
                f"{failure_code}."
            ),
            field_key=field_key,
            affected_value=affected_value,
            evidence=page.evidence,
            business_impact=business_impact,
            remediation_type=remediation_type,
            failure_codes=(failure_code,),
        )
    return RuleEvaluation(
        rule_version_id=rule_version_id,
        rule_key=rule_key,
        product_id=page.page_id,
        variant_id=None,
        field_key=field_key,
        check_key=check_key,
        dimension=dimension,
        severity=severity,
        weight=SEVERITY_WEIGHTS[severity],
        outcome="passed" if passed else "failed",
        coverage_basis_points=page.source_coverage_basis_points,
        finding=finding,
    )


def _normalized_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return ""
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE))
