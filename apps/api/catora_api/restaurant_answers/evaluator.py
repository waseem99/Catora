from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from catora_api.restaurant_answers.models import (
    AnswerState,
    RestaurantAnswerRunSnapshot,
    RestaurantFactEvidence,
    RestaurantQuestionDefinition,
    RestaurantQuestionEvaluation,
    RestaurantQuestionSuite,
)

_SUITE_KEY = "restaurant_operator_questions"
_SUITE_VERSION = "2026-08-01.v1"

_QUESTIONS = (
    RestaurantQuestionDefinition(
        key="brand_identity",
        question="What is the restaurant brand called?",
        entity_type="brand",
        required_fact_keys=("brand.name",),
    ),
    RestaurantQuestionDefinition(
        key="location_address",
        question="Where is this restaurant location?",
        entity_type="location",
        required_fact_keys=("location.name", "location.address"),
        optional_fact_keys=("location.landmark",),
    ),
    RestaurantQuestionDefinition(
        key="location_phone",
        question="How can a customer contact this location?",
        entity_type="location",
        required_fact_keys=("location.phone",),
    ),
    RestaurantQuestionDefinition(
        key="opening_hours",
        question="When is this location open?",
        entity_type="location",
        required_fact_keys=("location.hours",),
        optional_fact_keys=("location.special_hours",),
    ),
    RestaurantQuestionDefinition(
        key="service_modes",
        question="Does this location offer dine-in, takeaway, or delivery?",
        entity_type="location",
        required_fact_keys=("location.service_modes",),
    ),
    RestaurantQuestionDefinition(
        key="delivery_area",
        question="Which areas does this location deliver to?",
        entity_type="location",
        required_fact_keys=("location.service_areas",),
    ),
    RestaurantQuestionDefinition(
        key="facilities",
        question="Which customer facilities are available at this location?",
        entity_type="location",
        required_fact_keys=("location.facilities",),
    ),
    RestaurantQuestionDefinition(
        key="menu_availability",
        question="Which menu is currently available at this location?",
        entity_type="menu",
        required_fact_keys=("menu.name", "menu.availability"),
    ),
    RestaurantQuestionDefinition(
        key="menu_item_price",
        question="What is the current price of this menu item?",
        entity_type="menu_item",
        required_fact_keys=("menu_item.name", "menu_item.price"),
        optional_fact_keys=("menu_item.currency",),
    ),
    RestaurantQuestionDefinition(
        key="dietary_suitability",
        question="Which dietary preferences does this menu item support?",
        entity_type="menu_item",
        required_fact_keys=("menu_item.dietary_tags",),
    ),
    RestaurantQuestionDefinition(
        key="halal_claim",
        question="Is this menu item supported by an approved halal claim?",
        entity_type="menu_item",
        required_fact_keys=("menu_item.halal_claim",),
    ),
    RestaurantQuestionDefinition(
        key="allergen_information",
        question="Which allergens are declared for this menu item?",
        entity_type="menu_item",
        required_fact_keys=("menu_item.allergens",),
    ),
    RestaurantQuestionDefinition(
        key="current_offer",
        question="Is there a current approved offer for this item or location?",
        entity_type="location",
        required_fact_keys=("offer.name", "offer.validity"),
        optional_fact_keys=("offer.terms",),
    ),
)


def restaurant_question_suite() -> RestaurantQuestionSuite:
    payload = {
        "contract_version": "restaurant-answer-evaluation/v1",
        "suite_key": _SUITE_KEY,
        "suite_version": _SUITE_VERSION,
        "questions": [question.model_dump(mode="json") for question in _QUESTIONS],
    }
    return RestaurantQuestionSuite(
        **payload,
        suite_sha256=_sha256(payload),
    )


def evaluate_restaurant_questions(
    *,
    entity_type: str,
    entity_id: UUID,
    evidence: tuple[RestaurantFactEvidence, ...],
    as_of: datetime | None = None,
    suite: RestaurantQuestionSuite | None = None,
) -> RestaurantAnswerRunSnapshot:
    evaluated_at = as_of or datetime.now(UTC)
    if evaluated_at.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    selected_suite = suite or restaurant_question_suite()
    matching_questions = tuple(
        question
        for question in selected_suite.questions
        if question.entity_type == entity_type
    )
    matching_evidence = tuple(
        item
        for item in evidence
        if item.entity_type == entity_type and item.entity_id == entity_id
    )
    results = tuple(
        _evaluate_question(
            question,
            entity_id=entity_id,
            evidence=matching_evidence,
            evaluated_at=evaluated_at,
        )
        for question in matching_questions
    )
    state_counts: dict[AnswerState, int] = {
        "supported": 0,
        "partial": 0,
        "unsupported": 0,
        "stale": 0,
        "conflicting": 0,
        "inaccessible": 0,
    }
    for result in results:
        state_counts[result.state] += 1
    input_payload = {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "evaluated_at": evaluated_at.isoformat(),
        "evidence": [
            item.model_dump(mode="json", exclude_none=True)
            for item in sorted(matching_evidence, key=lambda value: str(value.evidence_id))
        ],
    }
    return RestaurantAnswerRunSnapshot(
        suite_key=selected_suite.suite_key,
        suite_version=selected_suite.suite_version,
        suite_sha256=selected_suite.suite_sha256,
        entity_type=entity_type,  # type: ignore[arg-type]
        entity_id=entity_id,
        evaluated_at=evaluated_at,
        results=results,
        state_counts=state_counts,
        input_sha256=_sha256(input_payload),
    )


def _evaluate_question(
    question: RestaurantQuestionDefinition,
    *,
    entity_id: UUID,
    evidence: tuple[RestaurantFactEvidence, ...],
    evaluated_at: datetime,
) -> RestaurantQuestionEvaluation:
    by_key = {
        key: tuple(item for item in evidence if item.fact_key == key)
        for key in question.required_fact_keys
    }
    all_items = tuple(item for values in by_key.values() for item in values)
    evidence_ids = tuple(
        sorted({item.evidence_id for item in all_items}, key=str)
    )
    missing_keys = tuple(key for key, values in by_key.items() if not values)
    inaccessible_keys = tuple(
        key
        for key, values in by_key.items()
        if values and all(not item.accessible for item in values)
    )
    current_by_key = {
        key: tuple(
            item
            for item in values
            if item.accessible
            and not item.invalidated
            and (item.effective_at is None or item.effective_at <= evaluated_at)
            and (item.expires_at is None or item.expires_at > evaluated_at)
        )
        for key, values in by_key.items()
    }
    conflicting_keys = tuple(
        key
        for key, values in current_by_key.items()
        if len({_canonical_value(item.value) for item in values}) > 1
    )
    stale_keys = tuple(
        key
        for key, values in by_key.items()
        if values
        and not current_by_key[key]
        and any(item.accessible for item in values)
    )

    if inaccessible_keys:
        state: AnswerState = "inaccessible"
        rationale = "Required evidence is inaccessible for: " + ", ".join(inaccessible_keys)
    elif conflicting_keys:
        state = "conflicting"
        rationale = "Current approved evidence conflicts for: " + ", ".join(conflicting_keys)
    elif stale_keys:
        state = "stale"
        rationale = "Required evidence is expired or invalidated for: " + ", ".join(stale_keys)
    elif len(missing_keys) == len(question.required_fact_keys):
        state = "unsupported"
        rationale = "No approved evidence supports the required facts."
    elif missing_keys:
        state = "partial"
        rationale = "Approved evidence is missing required facts: " + ", ".join(missing_keys)
    else:
        state = "supported"
        rationale = "All required facts have current, accessible, non-conflicting evidence."

    return RestaurantQuestionEvaluation(
        question_key=question.key,
        question=question.question,
        entity_type=question.entity_type,
        entity_id=entity_id,
        state=state,
        rationale=rationale,
        evidence_ids=evidence_ids,
        fact_keys=question.required_fact_keys,
        evaluated_at=evaluated_at,
    )


def _canonical_value(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
