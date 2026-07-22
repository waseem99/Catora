from __future__ import annotations

import uuid
from collections.abc import Mapping

from catora_api.enrichment.errors import (
    InvalidProviderOutputError,
    ProviderContractError,
)
from catora_api.enrichment.provider import ProviderAdapter
from catora_api.enrichment.types import (
    CandidateProposal,
    ConfidenceBand,
    EnrichmentRequest,
    EvidenceReference,
    ValidatedCandidate,
)

_PROTECTED_FACT_TOKENS = frozenset(
    {
        "dimension",
        "width",
        "height",
        "depth",
        "length",
        "weight",
        "material",
        "warranty",
        "safety",
        "compliance",
        "capacity",
    }
)


def validate_provider_identity(
    provider: ProviderAdapter,
    *,
    provider_name: str,
    model_name: str,
) -> None:
    if provider_name != provider.provider_name:
        raise ProviderContractError("provider response identity does not match adapter")
    if model_name != provider.model_name:
        raise ProviderContractError("provider response model does not match adapter")


def validate_candidates(
    request: EnrichmentRequest,
    candidates: tuple[CandidateProposal, ...],
) -> tuple[ValidatedCandidate, ...]:
    allowed_fields = set(request.allowed_fields)
    locked_fields = set(request.brand_controls.locked_fields)
    source_index = {
        (item.source_record_id, item.field_path): item for item in request.sources
    }
    validated: list[ValidatedCandidate] = []
    seen_fields: set[str] = set()
    for candidate in candidates:
        field_key = str(candidate.field_key)
        if field_key in seen_fields:
            raise InvalidProviderOutputError(
                f"provider returned duplicate candidate field {field_key!r}"
            )
        seen_fields.add(field_key)
        if field_key not in allowed_fields:
            raise InvalidProviderOutputError(
                f"provider returned disallowed field {field_key!r}"
            )
        if field_key in locked_fields:
            raise InvalidProviderOutputError(
                f"provider attempted to modify locked field {field_key!r}"
            )
        _validate_evidence(candidate.evidence, source_index)
        _validate_brand_controls(request, candidate)
        confidence = _confidence(candidate)
        validated.append(
            ValidatedCandidate(
                field_key=candidate.field_key,
                proposed_value=candidate.proposed_value,
                evidence=candidate.evidence,
                inferred=candidate.inferred,
                evidence_conflict=candidate.evidence_conflict,
                claim_type=candidate.claim_type,
                explanation=candidate.explanation,
                confidence=confidence,
                requires_verification=_requires_verification(candidate, confidence),
            )
        )
    return tuple(validated)


def _validate_evidence(
    evidence: tuple[EvidenceReference, ...],
    source_index: Mapping[tuple[uuid.UUID, str], object],
) -> None:
    for item in evidence:
        if (item.source_record_id, item.field_path) not in source_index:
            raise InvalidProviderOutputError(
                "provider cited evidence that was not supplied in the request"
            )


def _validate_brand_controls(
    request: EnrichmentRequest,
    candidate: CandidateProposal,
) -> None:
    text_value = (
        candidate.proposed_value
        if isinstance(candidate.proposed_value, str)
        else None
    )
    if text_value is None:
        return
    maximum = request.brand_controls.maximum_lengths.get(candidate.field_key)
    if maximum is not None and len(text_value) > maximum:
        raise InvalidProviderOutputError(
            f"proposal for {candidate.field_key!r} exceeds maximum length"
        )
    folded = text_value.casefold()
    for claim in request.brand_controls.banned_claims:
        if claim.casefold() in folded:
            raise InvalidProviderOutputError(
                f"proposal for {candidate.field_key!r} contains banned claim"
            )
    for term in request.brand_controls.required_terms:
        if term.casefold() not in folded:
            raise InvalidProviderOutputError(
                f"proposal for {candidate.field_key!r} omits required terminology"
            )


def _confidence(candidate: CandidateProposal) -> ConfidenceBand:
    if candidate.inferred or candidate.evidence_conflict or not candidate.evidence:
        return "low"
    kinds = {item.kind for item in candidate.evidence}
    if kinds <= {"structured_field", "source_field"}:
        return "high"
    return "medium"


def _requires_verification(
    candidate: CandidateProposal,
    confidence: ConfidenceBand,
) -> bool:
    protected_fact = candidate.claim_type == "fact" and any(
        token in str(candidate.field_key) for token in _PROTECTED_FACT_TOKENS
    )
    return (
        candidate.evidence_conflict
        or candidate.inferred
        or (protected_fact and confidence != "high")
    )
