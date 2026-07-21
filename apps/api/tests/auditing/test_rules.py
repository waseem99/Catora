from __future__ import annotations

import uuid

import pytest

from catora_api.auditing.rules import (
    RuleSpecificationError,
    TaxonomyFieldRule,
    evaluate_catalog,
    evaluate_product,
)
from catora_api.auditing.scoring import calculate_health_score
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
    RuleEvaluation,
    VariantAuditSnapshot,
)
from catora_api.taxonomy.compiler import build_compile_plan
from catora_api.taxonomy.loader import load_bundled_taxonomy


def _rule(category_key: str, field_key: str) -> TaxonomyFieldRule:
    plan = build_compile_plan(load_bundled_taxonomy())
    category = next(item for item in plan.categories if item.key == category_key)
    field = next(item for item in category.fields if item.field_key == field_key)
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{category_key}:{field_key}"),
        rule_key=f"tax.{category_key}.{field_key}",
        rule_version=plan.version,
        specification={
            "category_key": category_key,
            "field_key": field_key,
            "requirement": field.requirement,
            "severity": "high" if field.requirement == "required" else "medium",
            "field": field.specification,
        },
    )


def _product(
    *,
    attributes: dict[str, AttributeSnapshot] | None = None,
    variants: tuple[VariantAuditSnapshot, ...] = (),
    coverage: int = 10000,
) -> ProductAuditSnapshot:
    return ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key="sofas_sectionals",
        attributes=attributes or {},
        variants=variants,
        source_coverage_basis_points=coverage,
    )


def test_missing_required_field_produces_reproducible_finding() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    snapshot = _product()

    first = evaluate_product(snapshot, (rule,))
    second = evaluate_product(snapshot, (rule,))

    assert first == second
    presence = next(item for item in first if item.check_key == "presence")
    assert presence.outcome == "failed"
    assert presence.finding is not None
    assert presence.finding.failure_codes == ("missing_value",)
    assert len(presence.finding.fingerprint) == 64
    assert presence.finding.business_impact == "data_quality"
    discovery = next(
        item for item in first if item.check_key == "discoverability_coverage"
    )
    assert discovery.outcome == "failed"
    assert discovery.finding is not None
    assert discovery.finding.fingerprint != presence.finding.fingerprint


def test_valid_canonical_value_passes_presence_validation_and_discovery() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    evidence = EvidenceSnapshot(
        source_record_id=uuid.uuid4(),
        field_path="product.width",
        excerpt="210 cm",
    )
    snapshot = _product(
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=2100.0,
                value_type="decimal",
                unit="mm",
                evidence=(evidence,),
            )
        }
    )

    evaluations = evaluate_product(snapshot, (rule,))

    assert {item.check_key for item in evaluations} == {
        "presence",
        "validation",
        "discoverability_coverage",
    }
    assert all(item.outcome == "passed" for item in evaluations)
    assert all(item.finding is None for item in evaluations)
    score = calculate_health_score(evaluations)
    assert score.overall.score_basis_points == 10000
    assert score.overall.confidence_basis_points == 10000


def test_range_and_unit_failures_share_stable_validation_fingerprint() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    snapshot = _product(
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=0.0,
                value_type="decimal",
                unit="cm",
            )
        }
    )

    first = evaluate_product(snapshot, (rule,))
    second = evaluate_product(snapshot, (rule,))
    validation = next(item for item in first if item.check_key == "validation")
    repeated = next(item for item in second if item.check_key == "validation")

    assert validation.outcome == "failed"
    assert validation.finding is not None
    assert validation.finding.failure_codes == ("below_minimum", "invalid_unit")
    assert validation.finding.remediation_type == "normalize_unit"
    assert repeated.finding is not None
    assert repeated.finding.fingerprint == validation.finding.fingerprint


def test_invalid_type_stops_range_checks_without_guessing() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    snapshot = _product(
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value="2100",
                value_type="string",
                unit="mm",
            )
        }
    )

    validation = next(
        item
        for item in evaluate_product(snapshot, (rule,))
        if item.check_key == "validation"
    )

    assert validation.finding is not None
    assert validation.finding.failure_codes == (
        "declared_type_mismatch",
        "invalid_type",
    )
    assert validation.finding.remediation_type == "correct_type"


def test_variant_requirement_fails_when_variant_scope_is_absent() -> None:
    rule = _rule("sofas_sectionals", "color")

    evaluation = next(
        item
        for item in evaluate_product(_product(), (rule,))
        if item.check_key == "presence"
    )

    assert evaluation.outcome == "failed"
    assert evaluation.finding is not None
    assert evaluation.finding.failure_codes == ("missing_variant_scope",)


def test_variant_requirement_is_scored_per_variant() -> None:
    rule = _rule("sofas_sectionals", "color")
    first_variant = VariantAuditSnapshot(
        variant_id=uuid.uuid4(),
        attributes={
            "color": AttributeSnapshot(
                key="color",
                value="Blue",
                value_type="string",
            )
        },
    )
    second_variant = VariantAuditSnapshot(variant_id=uuid.uuid4())
    snapshot = _product(variants=(first_variant, second_variant))

    evaluations = evaluate_product(snapshot, (rule,))
    presence = [item for item in evaluations if item.check_key == "presence"]

    assert len(presence) == 2
    assert [item.outcome for item in presence] == ["passed", "failed"]
    validation = [item for item in evaluations if item.check_key == "validation"]
    assert len(validation) == 1
    assert validation[0].dimension == "variant_quality"


def test_score_formula_exposes_weighted_denominator_and_coverage_confidence() -> None:
    rule_version_id = uuid.uuid4()
    product_id = uuid.uuid4()
    evaluations = (
        RuleEvaluation(
            rule_version_id=rule_version_id,
            rule_key="rule.high",
            product_id=product_id,
            variant_id=None,
            field_key="a",
            check_key="presence",
            dimension="completeness",
            severity="high",
            weight=60,
            outcome="passed",
            coverage_basis_points=10000,
        ),
        RuleEvaluation(
            rule_version_id=uuid.uuid4(),
            rule_key="rule.medium",
            product_id=product_id,
            variant_id=None,
            field_key="b",
            check_key="presence",
            dimension="completeness",
            severity="medium",
            weight=30,
            outcome="failed",
            coverage_basis_points=5000,
        ),
    )

    score = calculate_health_score(evaluations).overall

    assert score.eligible_weight == 90
    assert score.evaluated_weight == 90
    assert score.passed_weight == 60
    assert score.score_basis_points == 6667
    assert score.confidence_basis_points == 8333
    assert len(score.contributions) == 2


def test_rule_specification_rejects_mismatched_or_unsupported_contracts() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    plan = build_compile_plan(load_bundled_taxonomy())
    category = next(item for item in plan.categories if item.key == "sofas_sectionals")
    field = next(item for item in category.fields if item.field_key == "width_mm")
    specification = {
        "category_key": "sofas_sectionals",
        "field_key": "wrong_key",
        "requirement": "required",
        "severity": "high",
        "field": field.specification,
    }

    with pytest.raises(RuleSpecificationError, match="does not match"):
        TaxonomyFieldRule.from_specification(
            rule_version_id=rule.rule_version_id,
            rule_key=rule.rule_key,
            rule_version=rule.rule_version,
            specification=specification,
        )

    specification["field_key"] = "width_mm"
    specification["requirement"] = "optional"
    with pytest.raises(RuleSpecificationError, match="unsupported taxonomy requirement"):
        TaxonomyFieldRule.from_specification(
            rule_version_id=rule.rule_version_id,
            rule_key=rule.rule_key,
            rule_version=rule.rule_version,
            specification=specification,
        )


def test_ten_thousand_product_workload_is_deterministic() -> None:
    rule = _rule("sofas_sectionals", "width_mm")
    snapshots = tuple(
        ProductAuditSnapshot(
            product_id=uuid.uuid5(uuid.NAMESPACE_OID, str(index)),
            category_key="sofas_sectionals",
            attributes={
                "width_mm": AttributeSnapshot(
                    key="width_mm",
                    value=2100.0,
                    value_type="decimal",
                    unit="mm",
                )
            },
        )
        for index in range(10000)
    )

    evaluations = evaluate_catalog(snapshots, (rule,))

    assert len(evaluations) == 30000
    assert all(item.outcome == "passed" for item in evaluations)
    assert calculate_health_score(evaluations).overall.score_basis_points == 10000
