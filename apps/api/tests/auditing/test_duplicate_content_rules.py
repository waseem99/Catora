from __future__ import annotations

import time
import uuid

from catora_api.auditing._duplicate_index import (
    DuplicateContentRecord,
    build_duplicate_content_index,
)
from catora_api.auditing.duplicate_rules import duplicate_rule_key
from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_product
from catora_api.auditing.types import AttributeSnapshot, ProductAuditSnapshot

_CATEGORY = "sofas_sectionals"


def _record(
    index: int,
    *,
    title: str,
    description: str,
    category: str = _CATEGORY,
) -> DuplicateContentRecord:
    return DuplicateContentRecord(
        product_id=uuid.uuid5(uuid.NAMESPACE_URL, f"duplicate-product:{index}"),
        category_key=category,
        title=title,
        description=description,
    )


def _rule() -> TaxonomyFieldRule:
    return TaxonomyFieldRule.from_specification(
        rule_version_id=uuid.uuid5(uuid.NAMESPACE_URL, "duplicate-rule"),
        rule_key=duplicate_rule_key(_CATEGORY),
        rule_version="1.0.0",
        specification={
            "category_key": _CATEGORY,
            "field_key": "duplicate_content",
            "requirement": "recommended",
            "severity": "medium",
            "field": {
                "category_key": _CATEGORY,
                "key": "duplicate_content",
                "label": "Duplicate content",
                "scope": "product",
                "data_type": "object",
                "canonical_unit": None,
                "allowed_values": [],
                "markets": [],
                "constraints": {"duplicate_content_kind": "catalog_similarity"},
                "mapping": {},
            },
        },
    )


def test_exact_clusters_are_deterministic_and_category_scoped() -> None:
    description = (
        "A durable solid oak frame with deep cushions and removable covers "
        "for everyday family use."
    )
    records = (
        _record(1, title="Harbor Three Seat Sofa", description=description),
        _record(2, title="Harbor Three Seat Sofa", description=description),
        _record(3, title="Harbor Three Seat Sofa", description=description, category="chairs"),
    )

    first = build_duplicate_content_index(records)
    second = build_duplicate_content_index(tuple(reversed(records)))

    assert first == second
    assert first[records[0].product_id].failure_codes == (
        "description_exact_duplicate",
        "title_exact_duplicate",
    )
    assert first[records[2].product_id].failure_codes == ()


def test_near_title_match_requires_similarity_and_token_overlap() -> None:
    records = (
        _record(
            1,
            title="Harbor modular three seat sofa in natural linen",
            description=(
                "Unique description one with enough detail to remain outside exact "
                "grouping and explain construction materials."
            ),
        ),
        _record(
            2,
            title="Harbor modular three-seat sofa in natural linen",
            description=(
                "Unique description two with enough detail to remain outside exact "
                "grouping and explain cushion comfort."
            ),
        ),
        _record(
            3,
            title="Compact walnut bedside cabinet with drawer",
            description=(
                "A separate product description with unrelated vocabulary, dimensions, "
                "finish and intended room placement."
            ),
        ),
    )

    results = build_duplicate_content_index(records)

    assert "title_near_duplicate" in results[records[0].product_id].failure_codes
    assert results[records[2].product_id].failure_codes == ()


def test_rule_evaluation_emits_stable_evidence_ready_finding() -> None:
    product_id = uuid.uuid4()
    payload = {
        "failure_codes": ["title_exact_duplicate"],
        "peer_product_ids": [str(uuid.uuid4())],
        "match_counts": {"title_exact_duplicate": 1},
    }
    snapshot = ProductAuditSnapshot(
        product_id=product_id,
        category_key=_CATEGORY,
        attributes={
            "duplicate_content": AttributeSnapshot(
                key="duplicate_content",
                value=payload,
                value_type="object",
            )
        },
    )

    first = evaluate_product(snapshot, (_rule(),))[0]
    second = evaluate_product(snapshot, (_rule(),))[0]

    assert first == second
    assert first.outcome == "failed"
    assert first.finding is not None
    assert first.finding.failure_codes == ("title_exact_duplicate",)
    assert first.finding.remediation_type == "differentiate_product_content"
    assert first.finding.affected_value == payload


def test_exact_group_bounds_peer_samples() -> None:
    records = tuple(
        _record(
            index,
            title="Harbor modular four seat sectional sofa",
            description=(
                "The same sufficiently detailed description for a repeated catalog "
                "listing with identical copy and materials."
            ),
        )
        for index in range(50)
    )

    result = build_duplicate_content_index(records)[records[0].product_id]

    assert len(result.peer_samples) == 20
    assert result.match_counts["title_exact_duplicate"] == 49
    assert result.match_counts["description_exact_duplicate"] == 49


def test_ten_thousand_unique_records_remain_practical() -> None:
    records = tuple(
        _record(
            index,
            title=f"Model {index} handcrafted furniture collection item {index * 17}",
            description=(
                f"Product {index} uses material batch {index * 31} with dimensions {index + 100} "
                f"and a distinct care profile reference {index * 97} for deterministic testing."
            ),
            category=f"category-{index % 12}",
        )
        for index in range(10_000)
    )

    started = time.perf_counter()
    results = build_duplicate_content_index(records)
    duration = time.perf_counter() - started

    assert len(results) == 10_000
    assert all(not result.failure_codes for result in results.values())
    assert duration < 12.0
