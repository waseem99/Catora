from __future__ import annotations

import time
import uuid

import pytest
from pydantic import ValidationError

from catora_api.intents import (
    CanonicalFact,
    FactEvidence,
    IntentConstraint,
    IntentProductCandidate,
    SoftPreference,
    StructuredBuyerIntent,
    evaluate_intent,
)


def _evidence() -> tuple[FactEvidence, ...]:
    return (
        FactEvidence(
            source_record_id=uuid.uuid4(),
            field_path="product.dimensions.width",
            checksum="a" * 64,
        ),
    )


def _candidate(*facts: CanonicalFact, category: str | None = "sofas") -> IntentProductCandidate:
    return IntentProductCandidate(
        product_id=uuid.uuid4(),
        category_key=category,
        facts=facts,
    )


def _intent(*hard: IntentConstraint) -> StructuredBuyerIntent:
    return StructuredBuyerIntent(
        query="A compact sofa no wider than 210 cm",
        category_keys=("sofas",),
        hard_constraints=hard,
    )


def test_equivalent_units_produce_confident_match_with_evidence() -> None:
    intent = _intent(
        IntentConstraint(
            field_key="width",
            operator="less_than_or_equal",
            expected=210,
            unit="cm",
        )
    )
    evidence = _evidence()
    candidate = _candidate(
        CanonicalFact(
            field_key="width",
            value=2100,
            value_state="present",
            unit="mm",
            evidence=evidence,
        )
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "confident_match"
    assert result.hard_constraints[0].status == "supported"
    assert result.hard_constraints[0].evidence == evidence


def test_missing_width_cannot_be_confident_match() -> None:
    intent = _intent(
        IntentConstraint(
            field_key="width",
            operator="less_than_or_equal",
            expected=210,
            unit="cm",
        )
    )
    candidate = _candidate(
        CanonicalFact(
            field_key="width",
            value=None,
            value_state="unknown",
            unit="mm",
        )
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "possible_match_missing_data"
    assert result.missing_fields == ("width",)


def test_known_width_violation_is_non_match() -> None:
    intent = _intent(
        IntentConstraint(
            field_key="width",
            operator="less_than_or_equal",
            expected=210,
            unit="cm",
        )
    )
    candidate = _candidate(
        CanonicalFact(
            field_key="width",
            value=2200,
            value_state="present",
            unit="mm",
            evidence=_evidence(),
        )
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "non_match"
    assert result.violated_fields == ("width",)


def test_present_value_without_evidence_remains_possible_match() -> None:
    intent = _intent(IntentConstraint(field_key="material", operator="equals", expected="oak"))
    candidate = _candidate(
        CanonicalFact(
            field_key="material",
            value="oak",
            value_state="present",
            evidence=(),
        )
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "possible_match_missing_data"
    assert result.hard_constraints[0].status == "missing"


def test_category_states_distinguish_missing_from_known_mismatch() -> None:
    intent = _intent()

    missing = evaluate_intent(intent, _candidate(category=None))
    mismatch = evaluate_intent(intent, _candidate(category="dining_tables"))

    assert missing.status == "insufficient_category_data"
    assert missing.category_status == "missing"
    assert mismatch.status == "non_match"
    assert mismatch.category_status == "violated"


def test_soft_preference_score_is_weighted_and_does_not_change_hard_status() -> None:
    intent = StructuredBuyerIntent(
        query="A compact oak sofa in blue",
        category_keys=("sofas",),
        hard_constraints=(
            IntentConstraint(field_key="material", operator="equals", expected="oak"),
        ),
        soft_preferences=(
            SoftPreference(
                constraint=IntentConstraint(field_key="color", operator="equals", expected="blue"),
                weight=3,
            ),
            SoftPreference(
                constraint=IntentConstraint(
                    field_key="assembly_required", operator="equals", expected=False
                ),
                weight=1,
            ),
        ),
    )
    candidate = _candidate(
        CanonicalFact(
            field_key="material",
            value="Oak",
            value_state="present",
            evidence=_evidence(),
        ),
        CanonicalFact(
            field_key="color",
            value="Blue",
            value_state="present",
            evidence=_evidence(),
        ),
        CanonicalFact(
            field_key="assembly_required",
            value=True,
            value_state="present",
            evidence=_evidence(),
        ),
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "confident_match"
    assert result.soft_score_basis_points == 7_500



def test_range_constraints_can_share_a_field_and_deduplicate_output_fields() -> None:
    intent = _intent(
        IntentConstraint(
            field_key="width",
            operator="greater_than_or_equal",
            expected=180,
            unit="cm",
        ),
        IntentConstraint(
            field_key="width",
            operator="less_than_or_equal",
            expected=210,
            unit="cm",
        ),
    )
    candidate = _candidate(
        CanonicalFact(
            field_key="width",
            value=2200,
            value_state="present",
            unit="mm",
            evidence=_evidence(),
        )
    )

    result = evaluate_intent(intent, candidate)

    assert result.status == "non_match"
    assert [item.status for item in result.hard_constraints] == [
        "supported",
        "violated",
    ]
    assert result.violated_fields == ("width",)

def test_invalid_constraint_shapes_fail_closed() -> None:
    with pytest.raises(ValidationError, match="non-empty tuple"):
        IntentConstraint(field_key="color", operator="one_of", expected="blue")
    with pytest.raises(ValidationError, match="numeric value"):
        IntentConstraint(
            field_key="width",
            operator="less_than_or_equal",
            expected="small",
        )


def test_10000_products_by_50_intents_is_deterministic_and_bounded() -> None:
    evidence = _evidence()
    products = tuple(
        _candidate(
            CanonicalFact(
                field_key="width",
                value=1800 + index % 500,
                value_state="present",
                unit="mm",
                evidence=evidence,
            )
        )
        for index in range(10_000)
    )
    intents = tuple(
        _intent(
            IntentConstraint(
                field_key="width",
                operator="less_than_or_equal",
                expected=190 + index,
                unit="cm",
            )
        )
        for index in range(50)
    )

    started = time.perf_counter()
    counts = {"confident_match": 0, "non_match": 0}
    for intent in intents:
        for product in products:
            result = evaluate_intent(intent, product)
            counts[result.status] += 1
    elapsed = time.perf_counter() - started

    assert sum(counts.values()) == 500_000
    assert counts == {"confident_match": 336_800, "non_match": 163_200}
    assert elapsed < 30
