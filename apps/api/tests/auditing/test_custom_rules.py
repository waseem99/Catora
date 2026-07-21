from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from catora_api.auditing.custom_rules import (
    AUDIT_RULE_TYPES,
    CUSTOM_RELATIONAL_RULE_TYPE,
    CustomAuditRuleReferenceError,
    CustomAuditRuleService,
    build_custom_rule_specification,
    custom_rule_metadata,
    evaluate_custom_relationship_rules,
)
from catora_api.auditing.rules import TaxonomyFieldRule
from catora_api.auditing.types import (
    AttributeSnapshot,
    ProductAuditSnapshot,
    RuleEvaluation,
    VariantAuditSnapshot,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField
from catora_api.schemas.audit_rules import CustomAuditRuleCreateRequest

CATEGORY_KEY = "sofas_sectionals"


def _field_specification(
    key: str,
    *,
    scope: str = "product",
    data_type: str = "decimal",
    canonical_unit: str | None = "mm",
) -> dict[str, object]:
    return {
        "category_key": CATEGORY_KEY,
        "key": key,
        "label": key.replace("_", " ").title(),
        "scope": scope,
        "data_type": data_type,
        "canonical_unit": canonical_unit,
        "allowed_values": [],
        "markets": [],
        "constraints": {},
        "mapping": {},
    }


def _rule(specification: dict[str, object]) -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid4(),
        rule_key="custom.package_width_consistency",
        rule_version="1.0.0",
        specification=specification,
    )


def _relationship(evaluations: Sequence[RuleEvaluation]) -> RuleEvaluation:
    return next(item for item in evaluations if item.check_key == "cross_field_consistency")


def test_custom_rule_request_is_closed_and_rejects_numeric_self_reference() -> None:
    payload = {
        "key": "package_width_consistency",
        "name": "Package width consistency",
        "description": "Product width must not exceed package width.",
        "taxonomy_version": "1.0.0",
        "category_key": CATEGORY_KEY,
        "field_key": "width_mm",
        "relationship": "less_than_or_equal_to_field",
        "related_field_key": "width_mm",
        "severity": "high",
    }
    with pytest.raises(ValidationError, match="cannot reference their own field"):
        CustomAuditRuleCreateRequest.model_validate(payload)

    payload["related_field_key"] = "package_width_mm"
    payload["script"] = "return true"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CustomAuditRuleCreateRequest.model_validate(payload)


def test_relationship_only_evaluation_does_not_duplicate_field_checks() -> None:
    specification = build_custom_rule_specification(
        category_key=CATEGORY_KEY,
        field_key="width_mm",
        relationship="less_than_or_equal_to_field",
        related_field_key="package_width_mm",
        severity="high",
        field_specification=_field_specification("width_mm"),
        related_field_specification=_field_specification("package_width_mm"),
    )
    rule = _rule(specification)
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=CATEGORY_KEY,
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=2000.0,
                value_type="decimal",
                unit="mm",
            ),
            "package_width_mm": AttributeSnapshot(
                key="package_width_mm",
                value=1900.0,
                value_type="decimal",
                unit="mm",
            ),
        },
    )

    evaluations = evaluate_custom_relationship_rules(snapshot, (rule,))

    assert len(evaluations) == 1
    result = _relationship(evaluations)
    assert result.outcome == "failed"
    assert result.finding is not None
    assert result.finding.failure_codes == ("above_related_field",)
    assert {item.check_key for item in evaluations} == {"cross_field_consistency"}


def test_product_variant_match_uses_immutable_field_contracts() -> None:
    specification = build_custom_rule_specification(
        category_key=CATEGORY_KEY,
        field_key="color",
        relationship="matches_product_field",
        related_field_key="color",
        severity="medium",
        field_specification=_field_specification(
            "color",
            scope="variant",
            data_type="string",
            canonical_unit=None,
        ),
        related_field_specification=_field_specification(
            "color",
            scope="variant",
            data_type="string",
            canonical_unit=None,
        ),
    )
    rule = _rule(specification)
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=CATEGORY_KEY,
        attributes={
            "color": AttributeSnapshot(
                key="color",
                value="blue",
                value_type="string",
            )
        },
        variants=(
            VariantAuditSnapshot(
                variant_id=uuid.uuid4(),
                attributes={
                    "color": AttributeSnapshot(
                        key="color",
                        value="red",
                        value_type="string",
                    )
                },
            ),
        ),
    )

    result = _relationship(evaluate_custom_relationship_rules(snapshot, (rule,)))

    assert result.outcome == "failed"
    assert result.finding is not None
    assert result.finding.failure_codes == ("product_variant_mismatch",)
    assert result.dimension == "variant_quality"


def test_invalid_field_scope_type_and_unit_contracts_are_rejected() -> None:
    with pytest.raises(CustomAuditRuleReferenceError, match="two integer or decimal"):
        build_custom_rule_specification(
            category_key=CATEGORY_KEY,
            field_key="color",
            relationship="less_than_or_equal_to_field",
            related_field_key="package_width_mm",
            severity="medium",
            field_specification=_field_specification(
                "color",
                data_type="string",
                canonical_unit=None,
            ),
            related_field_specification=_field_specification("package_width_mm"),
        )

    with pytest.raises(CustomAuditRuleReferenceError, match="same canonical unit"):
        build_custom_rule_specification(
            category_key=CATEGORY_KEY,
            field_key="width_mm",
            relationship="less_than_or_equal_to_field",
            related_field_key="package_width_mm",
            severity="medium",
            field_specification=_field_specification("width_mm"),
            related_field_specification=_field_specification(
                "package_width_mm",
                canonical_unit="cm",
            ),
        )

    with pytest.raises(CustomAuditRuleReferenceError, match="variant or both-scope"):
        build_custom_rule_specification(
            category_key=CATEGORY_KEY,
            field_key="color",
            relationship="matches_product_field",
            related_field_key="finish",
            severity="medium",
            field_specification=_field_specification(
                "color",
                scope="product",
                data_type="string",
                canonical_unit=None,
            ),
            related_field_specification=_field_specification(
                "finish",
                scope="product",
                data_type="string",
                canonical_unit=None,
            ),
        )


def test_custom_rule_metadata_and_supported_rule_types_are_explicit() -> None:
    specification = build_custom_rule_specification(
        category_key=CATEGORY_KEY,
        field_key="width_mm",
        relationship="greater_than_or_equal_to_field",
        related_field_key="minimum_width_mm",
        severity="medium",
        field_specification=_field_specification("width_mm"),
        related_field_specification=_field_specification("minimum_width_mm"),
    )

    assert custom_rule_metadata(specification) == (
        "greater_than_or_equal_to_field",
        "minimum_width_mm",
    )
    assert AUDIT_RULE_TYPES == (
        "taxonomy_field_requirement",
        CUSTOM_RELATIONAL_RULE_TYPE,
    )


class RowResult:
    def __init__(self, rows: list[tuple[TaxonomyField, Category]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[TaxonomyField, Category]]:
        return self._rows


class CreateSession:
    def __init__(self, rows: list[tuple[TaxonomyField, Category]]) -> None:
        self._scalars = iter([None, None])
        self._rows = rows
        self.added: list[object] = []
        self.flushes = 0

    async def scalar(self, _statement: object) -> object | None:
        return next(self._scalars)

    async def execute(self, _statement: object) -> RowResult:
        return RowResult(self._rows)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1
        for item in self.added:
            if isinstance(item, RuleDefinition | RuleVersion) and item.id is None:
                item.id = uuid.uuid4()


@pytest.mark.asyncio
async def test_service_persists_an_immutable_closed_rule_version() -> None:
    workspace_id = uuid.uuid4()
    category = Category(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        parent_id=None,
        key=CATEGORY_KEY,
        label="Sofas and sectionals",
        taxonomy_version="1.0.0",
        is_immutable=True,
    )
    width = TaxonomyField(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        category_id=category.id,
        key="width_mm",
        label="Width",
        data_type="decimal",
        version="1.0.0",
        specification=_field_specification("width_mm"),
        is_immutable=True,
    )
    package_width = TaxonomyField(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        category_id=category.id,
        key="package_width_mm",
        label="Package width",
        data_type="decimal",
        version="1.0.0",
        specification=_field_specification("package_width_mm"),
        is_immutable=True,
    )
    session = CreateSession([(width, category), (package_width, category)])

    record = await CustomAuditRuleService().create(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        key="package_width_consistency",
        name="Package width consistency",
        description="Product width must not exceed package width.",
        taxonomy_version="1.0.0",
        category_key=CATEGORY_KEY,
        field_key="width_mm",
        relationship="less_than_or_equal_to_field",
        related_field_key="package_width_mm",
        severity="high",
    )

    assert record.definition.key == "custom.package_width_consistency"
    assert record.definition.rule_type == CUSTOM_RELATIONAL_RULE_TYPE
    assert record.version.is_immutable is True
    assert record.relationship == "less_than_or_equal_to_field"
    assert record.related_field_key == "package_width_mm"
    assert session.flushes == 2
    assert any(isinstance(item, RuleDefinition) for item in session.added)
    assert any(isinstance(item, RuleVersion) for item in session.added)
