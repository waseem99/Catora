from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest

from catora_api.auditing.content_rules import (
    CONTENT_RULE_TEMPLATES,
    ContentRuleConfigurationError,
    content_rule_keys,
    ensure_standard_content_rules,
    evaluate_content_quality_rule,
)
from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_product
from catora_api.auditing.service import _snapshot_bytes
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
    RuleEvaluation,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category

_CATEGORY_KEY = "sofas_sectionals"


def _rule(kind: str) -> TaxonomyFieldRule:
    template = next(item for item in CONTENT_RULE_TEMPLATES if item.kind == kind)
    field_key = template.field_key
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"content:{kind}"),
        rule_key=f"builtin.{_CATEGORY_KEY}.{kind}",
        rule_version="1.0.0",
        specification={
            "category_key": _CATEGORY_KEY,
            "field_key": field_key,
            "requirement": "recommended",
            "severity": template.severity,
            "field": {
                "category_key": _CATEGORY_KEY,
                "key": field_key,
                "label": field_key.title(),
                "scope": "product",
                "data_type": "string",
                "canonical_unit": None,
                "allowed_values": [],
                "markets": [],
                "constraints": dict(template.constraints),
                "mapping": {},
            },
        },
    )


def _snapshot(
    *,
    title: str,
    description: str | None,
    category_key: str = _CATEGORY_KEY,
) -> ProductAuditSnapshot:
    title_evidence = EvidenceSnapshot(
        source_record_id=uuid.uuid4(),
        field_path="product.title",
        excerpt=title,
    )
    attributes: dict[str, AttributeSnapshot] = {
        "title": AttributeSnapshot(
            key="title",
            value=title,
            value_type="string",
            evidence=(title_evidence,),
        )
    }
    if description is not None:
        attributes["description"] = AttributeSnapshot(
            key="description",
            value=description,
            value_type="string",
            evidence=(
                EvidenceSnapshot(
                    source_record_id=uuid.uuid4(),
                    field_path="product.descriptionHtml",
                    excerpt=description,
                ),
            ),
        )
    return ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=category_key,
        attributes=attributes,
    )


def _content_evaluation(
    evaluations: Sequence[RuleEvaluation],
    check_key: str,
) -> RuleEvaluation:
    return next(item for item in evaluations if item.check_key == check_key)


def test_high_quality_title_and_description_pass() -> None:
    snapshot = _snapshot(
        title="Arden Modular Three Seat Sofa",
        description=(
            "A modular three seat sofa with a kiln-dried timber frame, supportive cushions, "
            "removable covers and carefully finished seams for flexible everyday living."
        ),
    )

    evaluations = evaluate_product(
        snapshot,
        (_rule("title_quality"), _rule("description_quality")),
    )

    assert {item.check_key for item in evaluations} == {
        "title_quality",
        "description_quality",
    }
    assert all(item.outcome == "passed" for item in evaluations)
    assert all(item.finding is None for item in evaluations)


def test_title_failures_are_stable_and_evidence_backed() -> None:
    rule = _rule("title_quality")
    snapshot = _snapshot(
        title="PRODUCT PRODUCT PRODUCT",
        description="A sufficiently detailed product description for this catalog fixture.",
    )

    first = evaluate_content_quality_rule(snapshot, rule)
    second = evaluate_content_quality_rule(snapshot, rule)

    assert first == second
    assert first.finding is not None
    assert first.finding.failure_codes == (
        "title_all_caps",
        "title_generic",
        "title_repeated_terms",
    )
    assert first.finding.business_impact == "discoverability"
    assert first.finding.remediation_type == "rewrite_title"
    assert first.finding.evidence == snapshot.attributes["title"].evidence


def test_description_missing_and_low_quality_codes_are_deterministic() -> None:
    rule = _rule("description_quality")
    missing = evaluate_content_quality_rule(
        _snapshot(title="Arden Modular Sofa", description=None),
        rule,
    )
    duplicate = evaluate_content_quality_rule(
        _snapshot(title="Arden Modular Sofa", description="Arden Modular Sofa"),
        rule,
    )
    repeated = evaluate_content_quality_rule(
        _snapshot(
            title="Arden Modular Sofa",
            description="soft soft soft soft soft soft soft soft",
        ),
        rule,
    )

    assert missing.finding is not None
    assert missing.finding.failure_codes == ("description_missing",)
    assert duplicate.finding is not None
    assert duplicate.finding.failure_codes == (
        "description_duplicates_title",
        "description_too_short",
    )
    assert repeated.finding is not None
    assert repeated.finding.failure_codes == (
        "description_low_variety",
        "description_too_short",
    )


def test_content_rules_apply_only_to_their_immutable_category() -> None:
    evaluations = evaluate_product(
        _snapshot(
            title="PRODUCT PRODUCT PRODUCT",
            description=None,
            category_key="chairs_recliners",
        ),
        (_rule("title_quality"), _rule("description_quality")),
    )

    assert evaluations == ()


def test_title_value_and_evidence_participate_in_snapshot_hash() -> None:
    product_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    first = ProductAuditSnapshot(
        product_id=product_id,
        category_key=_CATEGORY_KEY,
        attributes={
            "title": AttributeSnapshot(
                key="title",
                value="Arden Modular Sofa",
                value_type="string",
                evidence=(
                    EvidenceSnapshot(
                        source_record_id=evidence_id,
                        field_path="product.title",
                        excerpt="Arden Modular Sofa",
                    ),
                ),
            )
        },
    )
    changed = ProductAuditSnapshot(
        product_id=product_id,
        category_key=_CATEGORY_KEY,
        attributes={
            "title": AttributeSnapshot(
                key="title",
                value="Arden Modular Corner Sofa",
                value_type="string",
                evidence=(
                    EvidenceSnapshot(
                        source_record_id=evidence_id,
                        field_path="product.title",
                        excerpt="Arden Modular Corner Sofa",
                    ),
                ),
            )
        },
    )

    assert _snapshot_bytes(first) != _snapshot_bytes(changed)


class ScalarCollection:
    def __init__(self, values: list[Category]) -> None:
        self._values = values

    def all(self) -> list[Category]:
        return self._values


class EnsureSession:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories
        self._scalars = iter([None] * (len(categories) * len(CONTENT_RULE_TEMPLATES) * 2))
        self.added: list[object] = []
        self.flushes = 0

    async def scalars(self, _statement: object) -> ScalarCollection:
        return ScalarCollection(self._categories)

    async def scalar(self, _statement: object) -> None:
        return next(self._scalars)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, RuleDefinition | RuleVersion) and value.id is None:
            value.id = uuid.uuid4()

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_standard_rules_are_created_per_immutable_category() -> None:
    workspace_id = uuid.uuid4()
    categories = [
        Category(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            parent_id=None,
            key="chairs_recliners",
            label="Chairs and recliners",
            taxonomy_version="1.0.0",
            is_immutable=True,
        ),
        Category(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            parent_id=None,
            key="sofas_sectionals",
            label="Sofas and sectionals",
            taxonomy_version="1.0.0",
            is_immutable=True,
        ),
    ]
    session = EnsureSession(categories)

    await ensure_standard_content_rules(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        taxonomy_version="1.0.0",
    )

    definitions = [item for item in session.added if isinstance(item, RuleDefinition)]
    versions = [item for item in session.added if isinstance(item, RuleVersion)]
    assert sorted(item.key for item in definitions) == sorted(
        content_rule_keys([item.key for item in categories])
    )
    assert len(versions) == 4
    assert all(item.is_immutable for item in versions)
    assert all(item.version == "1.0.0" for item in versions)


@pytest.mark.asyncio
async def test_standard_rule_bootstrap_requires_immutable_categories() -> None:
    session = EnsureSession([])

    with pytest.raises(ContentRuleConfigurationError, match="No immutable taxonomy categories"):
        await ensure_standard_content_rules(
            session,  # type: ignore[arg-type]
            workspace_id=uuid.uuid4(),
            taxonomy_version="1.0.0",
        )
