from __future__ import annotations

import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EnrichmentTask = Literal[
    "extract_attributes",
    "normalize_attributes",
    "improve_title",
    "improve_description",
    "generate_faqs",
    "generate_alt_text",
    "explain_improvement",
    "classify_category",
]
EvidenceKind = Literal[
    "structured_field",
    "source_field",
    "source_copy",
    "approved_image_text",
]
ClaimType = Literal["fact", "marketing_copy", "classification"]
ConfidenceBand = Literal["high", "medium", "low"]
FieldKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=150)]


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: uuid.UUID
    field_path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50_000)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    kind: EvidenceKind


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: uuid.UUID
    field_path: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=2_000)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    kind: EvidenceKind


class BrandControls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tone: str = Field(default="clear and factual", min_length=1, max_length=300)
    banned_claims: tuple[str, ...] = Field(default=(), max_length=100)
    required_terms: tuple[str, ...] = Field(default=(), max_length=100)
    locked_fields: tuple[FieldKey, ...] = Field(default=(), max_length=200)
    maximum_lengths: dict[FieldKey, int] = Field(default_factory=dict)

    @field_validator("banned_claims", "required_terms")
    @classmethod
    def reject_blank_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("brand-control terms must not be blank")
        if len(normalized) != len(set(item.casefold() for item in normalized)):
            raise ValueError("brand-control terms must be unique")
        return normalized

    @field_validator("locked_fields")
    @classmethod
    def reject_duplicate_locked_fields(
        cls,
        value: tuple[FieldKey, ...],
    ) -> tuple[FieldKey, ...]:
        if len(value) != len(set(value)):
            raise ValueError("locked_fields must be unique")
        return value

    @field_validator("maximum_lengths")
    @classmethod
    def validate_maximum_lengths(
        cls,
        value: dict[FieldKey, int],
    ) -> dict[FieldKey, int]:
        if any(limit < 1 or limit > 50_000 for limit in value.values()):
            raise ValueError("maximum_lengths values must be between 1 and 50000")
        return value


class EnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    task_type: EnrichmentTask
    allowed_fields: tuple[FieldKey, ...] = Field(min_length=1, max_length=200)
    original_values: dict[FieldKey, object] = Field(default_factory=dict)
    sources: tuple[SourceDocument, ...] = Field(min_length=1, max_length=200)
    brand_controls: BrandControls = Field(default_factory=BrandControls)

    @field_validator("allowed_fields")
    @classmethod
    def reject_duplicate_allowed_fields(
        cls,
        value: tuple[FieldKey, ...],
    ) -> tuple[FieldKey, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_fields must be unique")
        return value

    @field_validator("original_values")
    @classmethod
    def validate_original_values(
        cls,
        value: dict[FieldKey, object],
    ) -> dict[FieldKey, object]:
        for item in value.values():
            _validate_json_value(item)
        return value


class CandidateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: FieldKey
    proposed_value: object
    evidence: tuple[EvidenceReference, ...] = Field(default=(), max_length=100)
    inferred: bool = False
    evidence_conflict: bool = False
    claim_type: ClaimType
    explanation: str = Field(min_length=1, max_length=2_000)

    @field_validator("proposed_value")
    @classmethod
    def validate_proposed_value(cls, value: object) -> object:
        _validate_json_value(value)
        return value

    @model_validator(mode="after")
    def require_evidence_or_inference(self) -> Self:
        if not self.evidence and not self.inferred:
            raise ValueError("candidate must include evidence or set inferred=true")
        return self


class ProviderEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[CandidateProposal, ...] = Field(min_length=1, max_length=50)


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: uuid.UUID
    task_type: EnrichmentTask
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_fingerprint: str = Field(min_length=64, max_length=64)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_payload: dict[str, object]
    response_schema: dict[str, object]
    max_output_tokens: int = Field(ge=1, le=32_000)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_name: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    output: dict[str, object]
    usage: ProviderUsage


class ValidatedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: FieldKey
    proposed_value: object
    evidence: tuple[EvidenceReference, ...]
    inferred: bool
    evidence_conflict: bool
    claim_type: ClaimType
    explanation: str
    confidence: ConfidenceBand
    requires_verification: bool

    @field_validator("proposed_value")
    @classmethod
    def validate_proposed_value(cls, value: object) -> object:
        _validate_json_value(value)
        return value


class EnrichmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: uuid.UUID
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    task_type: EnrichmentTask
    provider_name: str
    model_name: str
    prompt_version: str
    prompt_fingerprint: str = Field(min_length=64, max_length=64)
    attempt_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microunits: int = Field(ge=0)
    candidates: tuple[ValidatedCandidate, ...]


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 20:
        raise ValueError("JSON value exceeds maximum nesting depth")
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError(f"unsupported JSON value type {type(value).__name__}")
