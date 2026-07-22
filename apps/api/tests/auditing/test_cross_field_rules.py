from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest

from catora_api.auditing.rules import (
    RuleSpecificationError,
    TaxonomyFieldRule,
    evaluate_product,
)
from catora_api.auditing.types import (
    AttributeSnapshot,
    ProductAuditSnapshot,
    RuleEvaluation,
    VariantAuditSnapshot,
)


def _rule(
    *,
    field_key: str,
    data_type: str = "decimal",
    scope: str = "product",
    constraints: dict[str, object] | None = None,
) -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"cross-field:{field_key}:{scope}",
        ),
        rule_key=f"tax.sofas_sectionals.{field_key}",
        rule_version="1.0.0",
        specification={
            "category_key": "sofas_sectionals",
            "field_key": field_key,
            "requirement": "required",
            "severity": "high",
            "field": {
                "category_key": "sofas_sectionals",
                "key": field_key,
                "label": field_key,
                "scope": scope,
                "data_type": data_type,
                "canonical_unit": "mm" if data_type == "decimal" else None,
                "allowed_values": [],
                "markets": [],
                "constraints": constraints or {},
                "mapping": {},
            },
        },
    )


def _attribute(
    key: str,
    value: object,
    *,
    unit: str | None = "mm",
    value_type: str = "decimal",
) -> AttributeSnapshot:
    return AttributeSnapshot(
        key=key,
        value=value,  # type: ignore[arg-type]
        value_type=value_type,
        unit=unit,
    )


def _product(
    *,
    attributes: dict[str, AttributeSnapshot],
    variants: tuple[VariantAuditSnapshot, ...] = (),
) -> ProductAuditSnapshot:
    return ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key="sofas_sectionals",
        attributes=attributes,
        variants=variants,
    )


def _relationship(
    evaluations: Sequence[RuleEvaluation],
) -> RuleEvaluation:
    return next(
        item
        for item in evaluations
        if item.check_key == "cross_field_consistency"
    )


def test_numeric_relation_passes_and_fails_deterministically() -> None:
    width_rule = _rule(
        field_key="width_mm",
        constraints={"less_than_or_equal_to_field": "package_width_mm"},
    )
    passing = _product(
        attributes={
            "width_mm": _attribute("width_mm", 1800.0),
            "package_width_mm": _attribute("package_width_mm", 1900.0),
        }
    )
    failing = _product(
        attributes={
            "width_mm": _attribute("width_mm", 2000.0),
            "package_width_mm": _attribute("package_width_mm", 1900.0),
        }
    )

    assert _relationship(evaluate_product(passing, (width_rule,))).outcome == "passed"
    result = _relationship(evaluate_product(failing, (width_rule,)))
    repeated = _relationship(evaluate_product(failing, (width_rule,)))

    assert result.outcome == "failed"
    assert result.finding is not None
    assert result.finding.failure_codes == ("above_related_field",)
    assert result.finding.remediation_type == "reconcile_related_values"
    assert repeated.finding == result.finding


def test_missing_related_value_is_not_evaluated() -> None:
    width_rule = _rule(
        field_key="width_mm",
        constraints={"less_than_or_equal_to_field": "package_width_mm"},
    )
    snapshot = _product(
        attributes={"width_mm": _attribute("width_mm", 1800.0)}
    )

    result = _relationship(evaluate_product(snapshot, (width_rule,)))

    assert result.outcome == "not_evaluated"
    assert result.finding is None


def test_unit_mismatch_is_explicit_and_not_silently_compared() -> None:
    width_rule = _rule(
        field_key="width_mm",
        constraints={"less_than_or_equal_to_field": "package_width_mm"},
    )
    snapshot = _product(
        attributes={
            "width_mm": _attribute("width_mm", 1800.0, unit="mm"),
            "package_width_mm": _attribute(
                "package_width_mm",
                190.0,
                unit="cm",
            ),
        }
    )

    result = _relationship(evaluate_product(snapshot, (width_rule,)))

    assert result.outcome == "failed"
    assert result.finding is not None
    assert result.finding.failure_codes == ("related_field_unit_mismatch",)


def test_variant_can_match_same_canonical_product_field() -> None:
    color_rule = _rule(
        field_key="color",
        data_type="string",
        scope="variant",
        constraints={"matches_product_field": "color"},
    )
    matching = VariantAuditSnapshot(
        variant_id=uuid.uuid4(),
        attributes={
            "color": _attribute(
                "color",
                "blue",
                unit=None,
                value_type="string",
            )
        },
    )
    conflicting = VariantAuditSnapshot(
        variant_id=uuid.uuid4(),
        attributes={
            "color": _attribute(
                "color",
                "red",
                unit=None,
                value_type="string",
            )
        },
    )
    snapshot = _product(
        attributes={
            "color": _attribute(
                "color",
                "blue",
                unit=None,
                value_type="string",
            )
        },
        variants=(matching, conflicting),
    )

    relationships = [
        item
        for item in evaluate_product(snapshot, (color_rule,))
        if item.check_key == "cross_field_consistency"
    ]

    assert [item.outcome for item in relationships] == ["passed", "failed"]
    assert relationships[1].finding is not None
    assert relationships[1].finding.failure_codes == (
        "product_variant_mismatch",
    )
    assert relationships[1].dimension == "variant_quality"


def test_invalid_relationship_contracts_are_rejected() -> None:
    with pytest.raises(RuleSpecificationError, match="numeric field"):
        _rule(
            field_key="color",
            data_type="string",
            constraints={"less_than_or_equal_to_field": "package_width_mm"},
        )
    with pytest.raises(RuleSpecificationError, match="own field"):
        _rule(
            field_key="width_mm",
            constraints={"less_than_or_equal_to_field": "width_mm"},
        )
    with pytest.raises(RuleSpecificationError, match="variant or both"):
        _rule(
            field_key="color",
            data_type="string",
            scope="product",
            constraints={"matches_product_field": "product_color"},
        )
    with pytest.raises(RuleSpecificationError, match="canonical field key"):
        _rule(
            field_key="width_mm",
            constraints={"less_than_or_equal_to_field": "Bad field"},
        )
