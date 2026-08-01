from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from catora_api.reputation.models import ReviewAnalysis, ReviewObservation, ReviewResponseDraft

_THEME_TERMS: dict[str, tuple[str, ...]] = {
    "food_quality": ("taste", "tasty", "fresh", "cold", "stale", "undercooked", "burnt"),
    "service": ("service", "staff", "waiter", "rude", "friendly", "slow"),
    "delivery": ("delivery", "late", "rider", "packaging", "leak", "missing item"),
    "cleanliness": ("clean", "dirty", "hygiene", "smell", "washroom"),
    "value": ("price", "expensive", "value", "portion", "deal"),
    "accuracy": ("wrong order", "missing", "incorrect", "different"),
}
_RISK_TERMS: dict[str, tuple[str, ...]] = {
    "food_safety": ("food poisoning", "sick", "ill", "raw chicken", "contamination"),
    "allergen": ("allergy", "allergic", "allergen", "anaphylaxis"),
    "threat": ("threat", "violence", "harass", "stalk"),
    "legal": ("lawsuit", "lawyer", "legal action", "police"),
    "discrimination": ("racist", "discrimination", "harassment"),
}
_POSITIVE_TERMS = ("excellent", "great", "amazing", "delicious", "friendly", "fast", "clean")
_NEGATIVE_TERMS = ("bad", "terrible", "awful", "rude", "slow", "cold", "dirty", "late")
_WORDS = re.compile(r"\b[\w'-]+\b", flags=re.UNICODE)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def analyze_review(review: ReviewObservation) -> ReviewAnalysis:
    text = (review.text or "").casefold()
    themes: list[str] = []
    concerns: list[str] = []
    praise: list[str] = []
    evidence_terms: set[str] = set()
    for theme, terms in _THEME_TERMS.items():
        matched = sorted(term for term in terms if term in text)
        if matched:
            themes.append(theme)
            evidence_terms.update(matched)
    for term in _POSITIVE_TERMS:
        if term in text:
            praise.append(term)
            evidence_terms.add(term)
    for term in _NEGATIVE_TERMS:
        if term in text:
            concerns.append(term)
            evidence_terms.add(term)
    escalation: list[str] = []
    for risk, terms in _RISK_TERMS.items():
        matched = sorted(term for term in terms if term in text)
        if matched:
            escalation.append(risk)
            evidence_terms.update(matched)
    if review.rating <= 2 and not concerns:
        concerns.append("low_rating_without_textual_reason")
    if escalation:
        risk_level = "critical" if any(item in {"food_safety", "allergen", "threat"} for item in escalation) else "high"
    elif review.rating == 1:
        risk_level = "high"
    elif review.rating == 2:
        risk_level = "medium"
    elif review.rating == 3:
        risk_level = "low"
    else:
        risk_level = "none"
    fingerprint = canonical_hash(
        {
            "version": "reputation-rules/v1",
            "review_hash": review.observation_hash,
            "themes": sorted(themes),
            "praise": sorted(set(praise)),
            "concerns": sorted(set(concerns)),
            "risk_level": risk_level,
            "escalation": sorted(escalation),
        }
    )
    return ReviewAnalysis(
        themes=tuple(sorted(themes)),
        praise=tuple(sorted(set(praise))),
        concerns=tuple(sorted(set(concerns))),
        risk_level=risk_level,  # type: ignore[arg-type]
        escalation_reasons=tuple(sorted(escalation)),
        evidence_terms=tuple(sorted(evidence_terms)),
        fingerprint=fingerprint,
    )


def draft_review_response(
    review: ReviewObservation,
    analysis: ReviewAnalysis,
    *,
    review_id: object,
    restaurant_name: str,
    policy_version: str = "restaurant-review-response/v1",
) -> ReviewResponseDraft:
    from uuid import UUID

    if not isinstance(review_id, UUID):
        raise ValueError("review_id must be a UUID")
    if analysis.escalation_reasons:
        raise ValueError("Escalated reviews cannot receive an automatic response draft")
    if not review.text:
        raise ValueError("Review text is required for a response draft")
    if review.rating >= 4:
        draft = (
            f"Thank you for sharing your experience with {restaurant_name}. "
            "We appreciate your feedback and are glad the visit went well."
        )
    else:
        issue = analysis.themes[0].replace("_", " ") if analysis.themes else "your experience"
        draft = (
            f"Thank you for sharing this feedback with {restaurant_name}. "
            f"We are sorry that {issue} did not meet expectations. "
            "A manager should review the details before this response is approved."
        )
    return ReviewResponseDraft(
        review_id=review_id,
        policy_version=policy_version,
        draft_text=draft,
        evidence_review_hash=review.observation_hash,
    )


def aggregate_review_themes(
    analyses: tuple[ReviewAnalysis, ...],
) -> dict[str, dict[str, int]]:
    theme_counts: dict[str, int] = defaultdict(int)
    risk_counts: dict[str, int] = defaultdict(int)
    for analysis in analyses:
        for theme in analysis.themes:
            theme_counts[theme] += 1
        risk_counts[analysis.risk_level] += 1
    return {
        "themes": dict(sorted(theme_counts.items())),
        "risks": dict(sorted(risk_counts.items())),
    }


def word_count(value: str) -> int:
    return len(_WORDS.findall(value))
