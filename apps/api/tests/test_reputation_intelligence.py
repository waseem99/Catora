from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from catora_api.reputation import (
    ReviewObservation,
    ReviewProviderCapability,
    aggregate_review_themes,
    analyze_review,
    draft_review_response,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _review(*, rating: int = 5, text: str = "Amazing food and friendly staff") -> ReviewObservation:
    return ReviewObservation(
        external_review_id="review-1",
        external_location_id="location-1",
        restaurant_location_id=uuid.uuid4(),
        rating=rating,
        text=text,
        language="en",
        reviewer_display_name="Public reviewer",
        review_created_at=NOW,
        review_state="published",
        observed_at=NOW,
        observation_hash=hashlib.sha256(f"{rating}:{text}".encode()).hexdigest(),
    )


def test_review_posting_capability_cannot_be_presented_as_live() -> None:
    with pytest.raises(ValidationError, match="posting is unavailable"):
        ReviewProviderCapability(
            operation="create_reply",
            state="documented",
            read_only=False,
        )


def test_positive_review_analysis_and_draft_are_evidence_backed() -> None:
    review = _review()
    analysis = analyze_review(review)
    assert analysis.risk_level == "none"
    assert "food_quality" in analysis.themes
    assert "service" in analysis.themes
    draft = draft_review_response(
        review,
        analysis,
        review_id=uuid.uuid4(),
        restaurant_name="North Grill",
    )
    assert draft.requires_human_approval is True
    assert draft.posting_allowed is False
    assert draft.evidence_review_hash == review.observation_hash


def test_food_safety_review_requires_escalation_and_no_draft() -> None:
    review = _review(
        rating=1,
        text="The raw chicken made me sick and this looks like food poisoning.",
    )
    analysis = analyze_review(review)
    assert analysis.risk_level == "critical"
    assert "food_safety" in analysis.escalation_reasons
    with pytest.raises(ValueError, match="cannot receive"):
        draft_review_response(
            review,
            analysis,
            review_id=uuid.uuid4(),
            restaurant_name="North Grill",
        )


def test_empty_low_rating_review_is_not_fabricated() -> None:
    review = _review(rating=1, text="")
    analysis = analyze_review(review)
    assert analysis.concerns == ("low_rating_without_textual_reason",)
    with pytest.raises(ValueError, match="text is required"):
        draft_review_response(
            review,
            analysis,
            review_id=uuid.uuid4(),
            restaurant_name="North Grill",
        )


def test_theme_aggregation_is_deterministic() -> None:
    analyses = (
        analyze_review(_review()),
        analyze_review(_review(rating=2, text="Slow delivery and cold food")),
    )
    assert aggregate_review_themes(tuple(reversed(analyses))) == aggregate_review_themes(
        analyses
    )


def test_reputation_tables_register_additively() -> None:
    from catora_api.db.base import Base
    from catora_api.db.models.reputation import (  # noqa: F401
        ReviewAnalysisRecord,
        ReviewObservationRecord,
        ReviewProviderAccount,
        ReviewResponseDraftRecord,
    )

    assert {
        "review_provider_accounts",
        "review_observations",
        "review_analyses",
        "review_response_drafts",
    }.issubset(Base.metadata.tables)
