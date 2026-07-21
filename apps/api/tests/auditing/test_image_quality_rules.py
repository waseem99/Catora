from __future__ import annotations

import uuid

import pytest

from catora_api.auditing.image_rules import (
    IMAGE_QUALITY_ALGORITHM_VERSION,
    ImageRuleConfigurationError,
    ensure_standard_image_rules,
    image_rule_keys,
)
from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_product
from catora_api.auditing.service import _snapshot_bytes
from catora_api.auditing.types import (
    AttributeSnapshot,
    EvidenceSnapshot,
    ProductAuditSnapshot,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category

_CATEGORY_KEY = "sofas_sectionals"


def _rule() -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "image-quality"),
        rule_key=f"builtin.{_CATEGORY_KEY}.image_quality",
        rule_version="1.0.0",
        specification={
            "category_key": _CATEGORY_KEY,
            "field_key": "images",
            "requirement": "recommended",
            "severity": "medium",
            "field": {
                "category_key": _CATEGORY_KEY,
                "key": "images",
                "label": "Images",
                "scope": "product",
                "data_type": "list",
                "canonical_unit": None,
                "allowed_values": [],
                "markets": [],
                "constraints": {
                    "image_quality_kind": "inventory_alt_text",
                    "min_image_count": 1,
                    "require_alt_text": True,
                    "min_alt_length": 5,
                    "max_alt_length": 300,
                },
                "mapping": {},
                "image_quality_algorithm_version": IMAGE_QUALITY_ALGORITHM_VERSION,
            },
        },
    )


def _snapshot(images: list[dict[str, object]]) -> ProductAuditSnapshot:
    evidence = EvidenceSnapshot(
        source_record_id=uuid.uuid4(),
        field_path="product.images",
        excerpt="https://example.test/sofa-front.jpg",
    )
    return ProductAuditSnapshot(
        product_id=uuid.uuid4(),
        category_key=_CATEGORY_KEY,
        attributes={
            "title": AttributeSnapshot(
                key="title",
                value="Arden Modular Sofa",
                value_type="string",
            ),
            "images": AttributeSnapshot(
                key="images",
                value=images,
                value_type="list",
                value_state="present" if images else "missing",
                evidence=(evidence,) if images else (),
            ),
        },
    )


def test_distinct_images_with_descriptive_alt_text_pass() -> None:
    evaluation = evaluate_product(
        _snapshot(
            [
                {
                    "url": "https://example.test/sofa-front.jpg",
                    "alt_text": "Front view of Arden modular sofa in blue fabric",
                    "checksum": "a" * 64,
                    "position": 0,
                    "variant_id": None,
                },
                {
                    "url": "https://example.test/sofa-side.jpg",
                    "alt_text": "Side view showing the solid timber legs",
                    "checksum": "b" * 64,
                    "position": 1,
                    "variant_id": None,
                },
            ]
        ),
        (_rule(),),
    )[0]

    assert evaluation.check_key == "image_quality"
    assert evaluation.outcome == "passed"
    assert evaluation.finding is None
    assert evaluation.coverage_basis_points == 10000


def test_missing_images_produce_a_stable_finding() -> None:
    rule = _rule()
    snapshot = _snapshot([])

    first = evaluate_product(snapshot, (rule,))[0]
    second = evaluate_product(snapshot, (rule,))[0]

    assert first == second
    assert first.finding is not None
    assert first.finding.failure_codes == ("image_missing",)
    assert first.finding.remediation_type == "improve_image_metadata"
    assert first.finding.business_impact == "discoverability"


def test_missing_duplicate_and_title_alt_text_are_reported_together() -> None:
    evaluation = evaluate_product(
        _snapshot(
            [
                {
                    "url": "https://example.test/sofa-front.jpg",
                    "alt_text": None,
                    "checksum": "a" * 64,
                    "position": 0,
                    "variant_id": None,
                },
                {
                    "url": "https://example.test/sofa-copy.jpg",
                    "alt_text": "Arden Modular Sofa",
                    "checksum": "a" * 64,
                    "position": 1,
                    "variant_id": None,
                },
            ]
        ),
        (_rule(),),
    )[0]

    assert evaluation.finding is not None
    assert evaluation.finding.failure_codes == (
        "image_alt_duplicates_title",
        "image_alt_missing",
        "image_duplicate",
    )
    assert evaluation.finding.evidence


def test_image_inventory_changes_participate_in_snapshot_hashing() -> None:
    product_id = uuid.uuid4()
    first = _snapshot(
        [
            {
                "url": "https://example.test/sofa-front.jpg",
                "alt_text": "Front view of Arden modular sofa",
                "checksum": "a" * 64,
                "position": 0,
                "variant_id": None,
            }
        ]
    )
    second = _snapshot(
        [
            {
                "url": "https://example.test/sofa-front.jpg",
                "alt_text": "Front view of Arden modular sofa in blue fabric",
                "checksum": "a" * 64,
                "position": 0,
                "variant_id": None,
            }
        ]
    )
    first = ProductAuditSnapshot(
        product_id=product_id,
        category_key=first.category_key,
        attributes=first.attributes,
    )
    second = ProductAuditSnapshot(
        product_id=product_id,
        category_key=second.category_key,
        attributes=second.attributes,
    )

    assert _snapshot_bytes(first) != _snapshot_bytes(second)


class ScalarCollection:
    def __init__(self, values: list[Category]) -> None:
        self._values = values

    def all(self) -> list[Category]:
        return self._values


class EnsureSession:
    def __init__(self, categories: list[Category]) -> None:
        self._categories = categories
        self._scalars = iter([None, None] * len(categories))
        self.added: list[object] = []

    async def scalars(self, _statement: object) -> ScalarCollection:
        return ScalarCollection(self._categories)

    async def scalar(self, _statement: object) -> None:
        return next(self._scalars)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, RuleDefinition | RuleVersion) and value.id is None:
            value.id = uuid.uuid4()

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_image_rule_is_created_per_immutable_category() -> None:
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

    await ensure_standard_image_rules(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        taxonomy_version="1.0.0",
    )

    definitions = [
        item for item in session.added if isinstance(item, RuleDefinition)
    ]
    versions = [item for item in session.added if isinstance(item, RuleVersion)]
    assert sorted(item.key for item in definitions) == sorted(
        image_rule_keys([item.key for item in categories])
    )
    assert len(versions) == len(categories)
    assert all(item.is_immutable for item in versions)


@pytest.mark.asyncio
async def test_image_rule_bootstrap_requires_immutable_categories() -> None:
    session = EnsureSession([])

    with pytest.raises(
        ImageRuleConfigurationError,
        match="No immutable taxonomy categories",
    ):
        await ensure_standard_image_rules(
            session,  # type: ignore[arg-type]
            workspace_id=uuid.uuid4(),
            taxonomy_version="1.0.0",
        )
