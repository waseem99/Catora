from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import TypeGuard

from catora_api.intents.types import (
    CanonicalFact,
    CategoryStatus,
    ConstraintEvaluation,
    ConstraintStatus,
    FactValue,
    IntentConstraint,
    IntentMatchResult,
    IntentMatchStatus,
    IntentProductCandidate,
    JsonScalar,
    SoftPreference,
    StructuredBuyerIntent,
)

_UNIT_FACTORS: dict[str, tuple[str, Decimal]] = {
    "mm": ("length", Decimal("1")),
    "cm": ("length", Decimal("10")),
    "m": ("length", Decimal("1000")),
    "in": ("length", Decimal("25.4")),
    "inch": ("length", Decimal("25.4")),
    "inches": ("length", Decimal("25.4")),
    "ft": ("length", Decimal("304.8")),
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "oz": ("mass", Decimal("28.349523125")),
    "lb": ("mass", Decimal("453.59237")),
    "lbs": ("mass", Decimal("453.59237")),
}


def evaluate_intent(
    intent: StructuredBuyerIntent,
    candidate: IntentProductCandidate,
) -> IntentMatchResult:
    category_status = _category_status(intent, candidate)
    if category_status == "missing":
        return _result(
            candidate,
            status="insufficient_category_data",
            category_status=category_status,
        )
    if category_status == "violated":
        return _result(
            candidate,
            status="non_match",
            category_status=category_status,
        )

    facts = {item.field_key: item for item in candidate.facts}
    hard = tuple(
        _evaluate_constraint(item, facts.get(item.field_key))
        for item in intent.hard_constraints
    )
    soft = tuple(
        _evaluate_constraint(item.constraint, facts.get(item.constraint.field_key))
        for item in intent.soft_preferences
    )
    status = _match_status(hard)
    missing_fields = _unique_fields(
        item.field_key for item in hard if item.status in {"missing", "conflicting"}
    )
    violated_fields = _unique_fields(
        item.field_key for item in hard if item.status == "violated"
    )
    return IntentMatchResult(
        product_id=candidate.product_id,
        variant_id=candidate.variant_id,
        status=status,
        category_status=category_status,
        hard_constraints=hard,
        soft_preferences=soft,
        soft_score_basis_points=_soft_score(intent.soft_preferences, soft),
        missing_fields=missing_fields,
        violated_fields=violated_fields,
    )


def _result(
    candidate: IntentProductCandidate,
    *,
    status: IntentMatchStatus,
    category_status: CategoryStatus,
) -> IntentMatchResult:
    return IntentMatchResult(
        product_id=candidate.product_id,
        variant_id=candidate.variant_id,
        status=status,
        category_status=category_status,
        hard_constraints=(),
        soft_preferences=(),
        soft_score_basis_points=0,
        missing_fields=(),
        violated_fields=(),
    )


def _category_status(
    intent: StructuredBuyerIntent,
    candidate: IntentProductCandidate,
) -> CategoryStatus:
    if not intent.category_keys:
        return "not_required"
    if candidate.category_key is None:
        return "missing"
    if candidate.category_key not in intent.category_keys:
        return "violated"
    return "supported"


def _match_status(evaluations: tuple[ConstraintEvaluation, ...]) -> IntentMatchStatus:
    if any(item.status == "violated" for item in evaluations):
        return "non_match"
    if any(item.status in {"missing", "conflicting"} for item in evaluations):
        return "possible_match_missing_data"
    return "confident_match"


def _soft_score(
    preferences: tuple[SoftPreference, ...],
    evaluations: tuple[ConstraintEvaluation, ...],
) -> int:
    total_weight = sum(item.weight for item in preferences)
    if total_weight == 0:
        return 0
    supported_weight = sum(
        preference.weight
        for preference, evaluation in zip(preferences, evaluations, strict=True)
        if evaluation.status == "supported"
    )
    return supported_weight * 10_000 // total_weight


def _evaluate_constraint(
    constraint: IntentConstraint,
    fact: CanonicalFact | None,
) -> ConstraintEvaluation:
    if fact is None or fact.value_state in {"missing", "unknown"}:
        return _evaluation(constraint, fact, status="missing")
    if fact.value_state == "conflicting":
        return _evaluation(constraint, fact, status="conflicting")
    if fact.value_state == "not_applicable":
        return _evaluation(constraint, fact, status="violated")
    if not fact.evidence:
        return _evaluation(constraint, fact, status="missing")
    comparison = _compare(constraint, fact)
    return _evaluation(constraint, fact, status=comparison)


def _evaluation(
    constraint: IntentConstraint,
    fact: CanonicalFact | None,
    *,
    status: ConstraintStatus,
) -> ConstraintEvaluation:
    return ConstraintEvaluation(
        field_key=constraint.field_key,
        operator=constraint.operator,
        status=status,
        expected=constraint.expected,
        expected_unit=constraint.unit,
        actual=fact.value if fact is not None else None,
        actual_unit=fact.unit if fact is not None else None,
        evidence=fact.evidence if fact is not None else (),
    )


def _compare(constraint: IntentConstraint, fact: CanonicalFact) -> ConstraintStatus:
    actual = fact.value
    if actual is None:
        return "missing"
    if constraint.operator == "contains":
        return _contains(actual, constraint.expected)
    expected_values = (
        constraint.expected if isinstance(constraint.expected, tuple) else (constraint.expected,)
    )
    comparisons = [
        _compare_scalar(
            actual,
            expected,
            operator=constraint.operator,
            actual_unit=fact.unit,
            expected_unit=constraint.unit,
        )
        for expected in expected_values
    ]
    if "supported" in comparisons:
        return "supported"
    if "conflicting" in comparisons:
        return "conflicting"
    return "violated"


def _contains(actual: FactValue, expected: object) -> ConstraintStatus:
    if not isinstance(expected, str):
        return "conflicting"
    needle = expected.casefold().strip()
    values = actual if isinstance(actual, tuple) else (actual,)
    for value in values:
        if isinstance(value, str) and needle in value.casefold():
            return "supported"
    return "violated"


def _compare_scalar(
    actual: FactValue,
    expected: JsonScalar,
    *,
    operator: str,
    actual_unit: str | None,
    expected_unit: str | None,
) -> ConstraintStatus:
    if actual is None:
        return "missing"
    actual_values: tuple[JsonScalar, ...] = (
        actual if isinstance(actual, tuple) else (actual,)
    )
    statuses = [
        _compare_atomic(
            value,
            expected,
            operator=operator,
            actual_unit=actual_unit,
            expected_unit=expected_unit,
        )
        for value in actual_values
        if value is not None
    ]
    if "supported" in statuses:
        return "supported"
    if "conflicting" in statuses:
        return "conflicting"
    return "violated"


def _compare_atomic(
    actual: JsonScalar,
    expected: JsonScalar,
    *,
    operator: str,
    actual_unit: str | None,
    expected_unit: str | None,
) -> ConstraintStatus:
    if _is_number(actual) and _is_number(expected):
        converted = _numeric_pair(actual, expected, actual_unit, expected_unit)
        if converted is None:
            return "conflicting"
        actual_number, expected_number = converted
        if operator in {"equals", "one_of"}:
            return "supported" if actual_number == expected_number else "violated"
        if operator == "less_than_or_equal":
            return "supported" if actual_number <= expected_number else "violated"
        if operator == "greater_than_or_equal":
            return "supported" if actual_number >= expected_number else "violated"
        return "conflicting"
    if actual_unit is not None or expected_unit is not None:
        return "conflicting"
    if operator not in {"equals", "one_of"}:
        return "conflicting"
    if isinstance(actual, str) and isinstance(expected, str):
        matches = actual.strip().casefold() == expected.strip().casefold()
    else:
        matches = type(actual) is type(expected) and actual == expected
    return "supported" if matches else "violated"


def _numeric_pair(
    actual: int | float,
    expected: int | float,
    actual_unit: str | None,
    expected_unit: str | None,
) -> tuple[Decimal, Decimal] | None:
    try:
        actual_number = Decimal(str(actual))
        expected_number = Decimal(str(expected))
    except InvalidOperation:
        return None
    if not actual_number.is_finite() or not expected_number.is_finite():
        return None
    if actual_unit is None and expected_unit is None:
        return actual_number, expected_number
    if actual_unit is None or expected_unit is None:
        return None
    actual_factor = _UNIT_FACTORS.get(actual_unit)
    expected_factor = _UNIT_FACTORS.get(expected_unit)
    if actual_factor is None or expected_factor is None:
        return None
    if actual_factor[0] != expected_factor[0]:
        return None
    return actual_number * actual_factor[1], expected_number * expected_factor[1]


def _unique_fields(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _is_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)
