from __future__ import annotations

import uuid

import pytest

from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_product
from catora_api.auditing.structured_rules import (
    STRUCTURED_DATA_ALGORITHM_VERSION,
    ensure_standard_structured_data_rules,
    structured_rule_key,
)
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
    VariantAuditSnapshot,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField

_CATEGORY_KEY = "sofas_sectionals"


def _rule(*, field_key: str = "width_mm", scope: str = "product") -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"structured:{_CATEGORY_KEY}:{field_key}:{scope}",
        ),
        rule_key=structured_rule_key(_CATEGORY_KEY, field_key),
        rule_version="1.0.0",
        specification={
            "category_key": _CATEGORY_KEY,
            "field_key": field_key,
            "requirement": "recommended",
            "severity": "medium",
            "field": {
                "category_key": _CATEGORY_KEY,
                "key": field_key,
                "label": field_key.replace("_", " ").title(),
                "scope": scope,
                "data_type": "decimal" if field_key == "width_mm" else "string",
                "canonical_unit": "mm" if field_key == "width_mm" else None,
                "allowed_values": [],
                "markets": [],
                "constraints": {
                    "structured_data_quality_kind": "evidence_coverage",
                    "accepted_path_tokens": [
                        "structured",
                        "jsonld",
                        "json_ld",
                        "schema_org",
                    ],
                    "schema_org_property": "width" if field_key == "width_mm" else "color",
                },
                "mapping": {
                    "schema_org_property": "width" if field_key == "width_mm" else "color"
                },
                "structured_data_algorithm_version": STRUCTURED_DATA_ALGORITHM_VERSION,
            },
        },
    )


def _attribute(*, field_path: str) -> AttributeSnapshot:
    return AttributeSnapshot(
        key="width_mm",
        value=2100.0,
        value_type="decimal",
        unit="mm",
        evidence=(
            EvidenceSnapshot(
                source_record_id=uuid.uuid4(),
                field_path=field_path,
                excerpt="2100",
            ),
        ),
    )


def test_product_value_with_json_ld_evidence_passes() -> None:
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
        attributes={"width_mm": _attribute(field_path="product.json_ld.width")},
    )

    evaluation = evaluate_product(snapshot, (_rule(),))[0]

    assert evaluation.check_key == "structured_data_coverage"
    assert evaluation.outcome == "passed"
    assert evaluation.finding is None
    assert evaluation.coverage_basis_points == 10000


def test_present_value_without_structured_evidence_fails_stably() -> None:
    rule = _rule()
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
        attributes={"width_mm": _attribute(field_path="product.description.width")},
    )

    first = evaluate_product(snapshot, (rule,))[0]
    second = evaluate_product(snapshot, (rule,))[0]

    assert first == second
    assert first.finding is not None
    assert first.finding.failure_codes == ("structured_data_evidence_missing",)
    assert first.finding.remediation_type == "add_structured_data_mapping"
    assert first.finding.business_impact == "discoverability"
    assert first.finding.evidence == snapshot.attributes["width_mm"].evidence


def test_unstructured_path_does_not_false_match_structured_token() -> None:
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
        attributes={"width_mm": _attribute(field_path="product.unstructured.width")},
    )

    evaluation = evaluate_product(snapshot, (_rule(),))[0]

    assert evaluation.outcome == "failed"
    assert evaluation.finding is not None
    assert evaluation.finding.failure_codes == ("structured_data_evidence_missing",)


def test_missing_value_is_not_evaluated_instead_of_duplicating_presence() -> None:
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
    )

    evaluation = evaluate_product(snapshot, (_rule(),))[0]

    assert evaluation.outcome == "not_evaluated"
    assert evaluation.finding is None


def test_variant_scope_is_evaluated_per_variant() -> None:
    first_variant = VariantAuditSnapshot(
        variant_id=uuid.uuid4(),
        attributes={
            "color": AttributeSnapshot(
                key="color",
                value="blue",
                value_type="string",
                evidence=(
                    EvidenceSnapshot(
                        source_record_id=uuid.uuid4(),
                        field_path="variant.schema_org.color",
                    ),
                ),
            )
        },
    )
    second_variant = VariantAuditSnapshot(
        variant_id=uuid.uuid4(),
        attributes={
            "color": AttributeSnapshot(
                key="color",
                value="red",
                value_type="string",
                evidence=(
                    EvidenceSnapshot(
                        source_record_id=uuid.uuid4(),
                        field_path="variant.option.color",
                    ),
                ),
            )
        },
    )
    snapshot = ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
        variants=(first_variant, second_variant),
    )

    evaluations = evaluate_product(snapshot, (_rule(field_key="color", scope="variant"),))

    assert [item.variant_id for item in evaluations] == [
        first_variant.variant_id,
        second_variant.variant_id,
    ]
    assert [item.outcome for item in evaluations] == ["passed", "failed"]


class RowResult:
    def __init__(self, rows: list[tuple[TaxonomyField, Category]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[TaxonomyField, Category]]:
        return self._rows


class EnsureSession:
    def __init__(self, rows: list[tuple[TaxonomyField, Category]]) -> None:
        self._rows = rows
        eligible_count = sum(
            1
            for field, _category in rows
            if field.specification.get("mapping", {}).get("schema_org_property")
            and field.specification.get("requirement") in {"required", "recommended"}
        )
        self._scalars = iter([None, None] * eligible_count)
        self.added: list[object] = []

    async def execute(self, _statement: object) -> RowResult:
        return RowResult(self._rows)

    async def scalar(self, _statement: object) -> None:
        return next(self._scalars)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, RuleDefinition | RuleVersion) and value.id is None:
            value.id = uuid.uuid4()

    async def flush(self) -> None:
        return None


def _field(
    *,
    workspace_id: uuid.UUID,
    category: Category,
    key: str,
    schema_property: str | None,
    requirement: str = "recommended",
) -> TaxonomyField:
    return TaxonomyField(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        category_id=category.id,
        key=key,
        label=key.replace("_", " ").title(),
        data_type="decimal" if key == "width_mm" else "string",
        version="1.0.0",
        specification={
            "category_key": category.key,
            "key": key,
            "label": key.replace("_", " ").title(),
            "scope": "product",
            "data_type": "decimal" if key == "width_mm" else "string",
            "canonical_unit": "mm" if key == "width_mm" else None,
            "allowed_values": [],
            "markets": [],
            "constraints": {},
            "requirement": requirement,
            "mapping": (
                {"schema_org_property": schema_property}
                if schema_property is not None
                else {}
            ),
        },
        is_immutable=True,
    )


@pytest.mark.asyncio
async def test_bootstrap_creates_rules_only_for_mapped_fields() -> None:
    workspace_id = uuid.uuid4()
    category = Category(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        parent_id=None,
        key=_CATEGORY_KEY,
        label="Sofas and sectionals",
        taxonomy_version="1.0.0",
        is_immutable=True,
    )
    width = _field(
        workspace_id=workspace_id,
        category=category,
        key="width_mm",
        schema_property="width",
    )
    finish = _field(
        workspace_id=workspace_id,
        category=category,
        key="finish",
        schema_property=None,
    )
    optional_color = _field(
        workspace_id=workspace_id,
        category=category,
        key="color",
        schema_property="color",
        requirement="optional",
    )
    session = EnsureSession(
        [(width, category), (finish, category), (optional_color, category)]
    )

    await ensure_standard_structured_data_rules(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        taxonomy_version="1.0.0",
    )

    definitions = [item for item in session.added if isinstance(item, RuleDefinition)]
    versions = [item for item in session.added if isinstance(item, RuleVersion)]
    assert [item.key for item in definitions] == [
        structured_rule_key(_CATEGORY_KEY, "width_mm")
    ]
    assert len(versions) == 1
    assert versions[0].is_immutable is True
    assert versions[0].specification["field"]["scope"] == "product"


@pytest.mark.asyncio
async def test_bootstrap_without_eligible_mappings_is_a_noop() -> None:
    workspace_id = uuid.uuid4()
    category = Category(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        parent_id=None,
        key=_CATEGORY_KEY,
        label="Sofas and sectionals",
        taxonomy_version="1.0.0",
        is_immutable=True,
    )
    finish = _field(
        workspace_id=workspace_id,
        category=category,
        key="finish",
        schema_property=None,
    )
    session = EnsureSession([(finish, category)])

    await ensure_standard_structured_data_rules(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        taxonomy_version="1.0.0",
    )

    assert session.added == []
