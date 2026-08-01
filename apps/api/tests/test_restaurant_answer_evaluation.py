from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from catora_api.db.base import Base
from catora_api.db.models.restaurant_answers import (  # noqa: F401
    RestaurantAnswerResult,
    RestaurantAnswerRun,
    RestaurantAnswerSuiteVersion,
    RestaurantExternalCitationObservation,
)
from catora_api.main import app
from catora_api.restaurant_answers import (
    ExternalCitationObservation,
    RestaurantFactEvidence,
    evaluate_restaurant_questions,
    restaurant_question_suite,
)

LOCATION_ID = uuid.UUID("4f79cbd1-707d-47d8-b9a0-6f70a7fe8d94")
OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _evidence(
    fact_key: str,
    value: object,
    *,
    evidence_id: str,
    expires_at: datetime | None = None,
    accessible: bool = True,
    invalidated: bool = False,
) -> RestaurantFactEvidence:
    return RestaurantFactEvidence(
        evidence_id=uuid.UUID(evidence_id),
        entity_type="location",
        entity_id=LOCATION_ID,
        fact_key=fact_key,
        value=value,  # type: ignore[arg-type]
        source_url="https://example.test/locations/lahore",
        source_checksum=hashlib.sha256(f"{fact_key}:{value}".encode()).hexdigest(),
        observed_at=OBSERVED_AT,
        expires_at=expires_at,
        accessible=accessible,
        invalidated=invalidated,
    )


def _state(snapshot: object, question_key: str) -> str:
    results = snapshot.results  # type: ignore[attr-defined]
    return next(result.state for result in results if result.question_key == question_key)


def test_suite_is_versioned_and_deterministic() -> None:
    first = restaurant_question_suite()
    second = restaurant_question_suite()
    assert first == second
    assert first.suite_sha256 == second.suite_sha256
    assert len(first.questions) >= 10
    assert {question.entity_type for question in first.questions} >= {
        "brand",
        "location",
        "menu",
        "menu_item",
    }


def test_current_complete_evidence_is_supported() -> None:
    snapshot = evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(
            _evidence(
                "location.name",
                "North Grill Lahore",
                evidence_id="bd55c02d-d221-4ca2-8c36-f90aa85d4608",
            ),
            _evidence(
                "location.address",
                "MM Alam Road, Lahore",
                evidence_id="1845ddc1-019c-4e46-8455-e3761b00a703",
            ),
        ),
        as_of=OBSERVED_AT + timedelta(hours=1),
    )
    assert _state(snapshot, "location_address") == "supported"
    assert snapshot.input_sha256 == evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(
            _evidence(
                "location.name",
                "North Grill Lahore",
                evidence_id="bd55c02d-d221-4ca2-8c36-f90aa85d4608",
            ),
            _evidence(
                "location.address",
                "MM Alam Road, Lahore",
                evidence_id="1845ddc1-019c-4e46-8455-e3761b00a703",
            ),
        ),
        as_of=OBSERVED_AT + timedelta(hours=1),
    ).input_sha256


def test_stale_conflicting_and_inaccessible_evidence_fail_closed() -> None:
    stale = evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(
            _evidence(
                "location.hours",
                {"monday": "10:00-22:00"},
                evidence_id="5c4654f3-4b2d-45bc-a46d-69eeec68b98a",
                expires_at=OBSERVED_AT + timedelta(hours=1),
            ),
        ),
        as_of=OBSERVED_AT + timedelta(days=1),
    )
    assert _state(stale, "opening_hours") == "stale"

    conflicting = evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(
            _evidence(
                "location.phone",
                "+92-42-111-111-111",
                evidence_id="ad112693-a109-4433-bf5c-f55a8c14c302",
            ),
            _evidence(
                "location.phone",
                "+92-42-222-222-222",
                evidence_id="4c6fa9ea-3cad-4db3-aa4e-e40fb49fa947",
            ),
        ),
        as_of=OBSERVED_AT + timedelta(hours=1),
    )
    assert _state(conflicting, "location_phone") == "conflicting"

    inaccessible = evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(
            _evidence(
                "location.facilities",
                ["parking"],
                evidence_id="58074a89-8aec-41af-8214-c9aa1ba198b0",
                accessible=False,
            ),
        ),
        as_of=OBSERVED_AT + timedelta(hours=1),
    )
    assert _state(inaccessible, "facilities") == "inaccessible"


def test_missing_evidence_is_not_rendered_as_zero_or_supported() -> None:
    snapshot = evaluate_restaurant_questions(
        entity_type="location",
        entity_id=LOCATION_ID,
        evidence=(),
        as_of=OBSERVED_AT,
    )
    assert snapshot.state_counts["unsupported"] == len(snapshot.results)
    assert not snapshot.state_counts["supported"]


def test_external_observation_is_separate_and_requires_verified_facts() -> None:
    with pytest.raises(ValueError, match="verified fact keys"):
        ExternalCitationObservation(
            provider="example-search",
            model_or_surface="answer-surface-v1",
            locale="en-PK",
            exact_query="Where is North Grill Lahore?",
            observed_at=OBSERVED_AT,
            response_sha256=hashlib.sha256(b"response").hexdigest(),
            cited_urls=("https://example.test/locations/lahore",),
            accuracy_state="accurate",
        )

    observation = ExternalCitationObservation(
        provider="example-search",
        model_or_surface="answer-surface-v1",
        locale="en-PK",
        exact_query="Where is North Grill Lahore?",
        observed_at=OBSERVED_AT,
        response_sha256=hashlib.sha256(b"response").hexdigest(),
        cited_urls=("https://example.test/locations/lahore",),
        accuracy_state="accurate",
        verified_fact_keys=("location.address",),
    )
    assert observation.provider == "example-search"


def test_tables_and_routes_are_registered() -> None:
    expected_tables = {
        "restaurant_answer_suite_versions",
        "restaurant_answer_runs",
        "restaurant_answer_results",
        "restaurant_external_citation_observations",
    }
    assert expected_tables.issubset(Base.metadata.tables)
    paths = app.openapi()["paths"]
    prefix = "/api/v1/workspaces/{workspace_id}/restaurant-answer-evaluations"
    assert f"{prefix}/suite" in paths
    assert f"{prefix}/runs" in paths
    assert f"{prefix}/runs/{{run_id}}" in paths
