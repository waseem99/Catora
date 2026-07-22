from __future__ import annotations

import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type JsonScalar = str | int | float | bool
type ConstraintExpected = JsonScalar | tuple[JsonScalar, ...]
type FactValue = JsonScalar | tuple[JsonScalar, ...] | None
FieldKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=150)]
IntentOperator = Literal[
    "equals",
    "one_of",
    "less_than_or_equal",
    "greater_than_or_equal",
    "contains",
]
ValueState = Literal["present", "missing", "unknown", "not_applicable", "conflicting"]
ConstraintStatus = Literal["supported", "missing", "violated", "conflicting"]
IntentMatchStatus = Literal[
    "confident_match",
    "possible_match_missing_data",
    "non_match",
    "insufficient_category_data",
]
CategoryStatus = Literal["not_required", "supported", "missing", "violated"]


class IntentConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: FieldKey
    operator: IntentOperator
    expected: ConstraintExpected
    unit: str | None = Field(default=None, min_length=1, max_length=30)

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        return value.strip().casefold() if value is not None else None

    @model_validator(mode="after")
    def validate_expected_shape(self) -> Self:
        if self.operator == "one_of":
            if not isinstance(self.expected, tuple) or not self.expected:
                raise ValueError("one_of constraints require a non-empty tuple")
        elif isinstance(self.expected, tuple):
            raise ValueError(f"{self.operator} constraints require a scalar expected value")
        if self.operator in {"less_than_or_equal", "greater_than_or_equal"}:
            if isinstance(self.expected, bool) or not isinstance(self.expected, int | float):
                raise ValueError(f"{self.operator} constraints require a numeric value")
        if self.operator == "contains" and not isinstance(self.expected, str):
            raise ValueError("contains constraints require a string value")
        return self


class SoftPreference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    constraint: IntentConstraint
    weight: int = Field(ge=1, le=100)


class StructuredBuyerIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=2_000)
    category_keys: tuple[str, ...] = Field(default=(), max_length=100)
    hard_constraints: tuple[IntentConstraint, ...] = Field(default=(), max_length=100)
    soft_preferences: tuple[SoftPreference, ...] = Field(default=(), max_length=100)
    market_id: uuid.UUID | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=35)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized

    @field_validator("category_keys")
    @classmethod
    def normalize_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if any(not item for item in normalized):
            raise ValueError("category keys must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("category keys must be unique")
        return normalized


class FactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: uuid.UUID
    field_path: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=2_000)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)


class CanonicalFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: FieldKey
    value: FactValue
    value_state: ValueState
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    evidence: tuple[FactEvidence, ...] = Field(default=(), max_length=100)

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        return value.strip().casefold() if value is not None else None

    @model_validator(mode="after")
    def validate_state_value(self) -> Self:
        if self.value_state == "present" and self.value is None:
            raise ValueError("present facts require a value")
        if self.value_state != "present" and self.value is not None:
            raise ValueError("non-present facts must not carry a value")
        return self


class IntentProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    category_key: str | None = Field(default=None, min_length=1, max_length=150)
    facts: tuple[CanonicalFact, ...] = Field(default=(), max_length=500)

    @field_validator("category_key")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        return value.strip().casefold() if value is not None else None

    @model_validator(mode="after")
    def reject_duplicate_facts(self) -> Self:
        keys = [item.field_key for item in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate fact field keys must be unique")
        return self


class ConstraintEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: FieldKey
    operator: IntentOperator
    status: ConstraintStatus
    expected: ConstraintExpected
    expected_unit: str | None
    actual: FactValue
    actual_unit: str | None
    evidence: tuple[FactEvidence, ...]


class IntentMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    category_key: str | None = Field(min_length=1, max_length=150)
    status: IntentMatchStatus
    category_status: CategoryStatus
    hard_constraints: tuple[ConstraintEvaluation, ...]
    soft_preferences: tuple[ConstraintEvaluation, ...]
    soft_score_basis_points: int = Field(ge=0, le=10_000)
    missing_fields: tuple[FieldKey, ...]
    violated_fields: tuple[FieldKey, ...]
