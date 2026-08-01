from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RESTAURANT_ANSWER_CONTRACT_VERSION: Literal["restaurant-answer-evaluation/v1"] = (
    "restaurant-answer-evaluation/v1"
)

AnswerState = Literal[
    "supported",
    "partial",
    "unsupported",
    "stale",
    "conflicting",
    "inaccessible",
]
RestaurantEntityType = Literal[
    "brand",
    "location",
    "service_area",
    "menu",
    "menu_item",
]
ExternalAccuracyState = Literal[
    "accurate",
    "partially_accurate",
    "inaccurate",
    "unverifiable",
]


class RestaurantAnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RestaurantQuestionDefinition(RestaurantAnswerModel):
    key: str = Field(pattern=r"^[a-z0-9_]{3,100}$")
    question: str = Field(min_length=5, max_length=500)
    entity_type: RestaurantEntityType
    required_fact_keys: tuple[str, ...] = Field(min_length=1, max_length=20)
    optional_fact_keys: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_fact_keys(self) -> RestaurantQuestionDefinition:
        keys = self.required_fact_keys + self.optional_fact_keys
        if len(keys) != len(set(keys)):
            raise ValueError("Question fact keys must be unique")
        return self


class RestaurantQuestionSuite(RestaurantAnswerModel):
    contract_version: Literal["restaurant-answer-evaluation/v1"] = (
        RESTAURANT_ANSWER_CONTRACT_VERSION
    )
    suite_key: str = Field(pattern=r"^[a-z0-9_]{3,100}$")
    suite_version: str = Field(min_length=1, max_length=100)
    questions: tuple[RestaurantQuestionDefinition, ...] = Field(
        min_length=1,
        max_length=100,
    )
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_question_keys(self) -> RestaurantQuestionSuite:
        keys = [question.key for question in self.questions]
        if len(keys) != len(set(keys)):
            raise ValueError("Question keys must be unique inside a suite")
        return self


FactValue = str | int | float | bool | list[str] | dict[str, str] | None


class RestaurantFactEvidence(RestaurantAnswerModel):
    evidence_id: UUID
    entity_type: RestaurantEntityType
    entity_id: UUID
    fact_key: str = Field(pattern=r"^[a-z0-9_.]{2,160}$")
    value: FactValue
    source_url: str | None = Field(default=None, max_length=2_000)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    accessible: bool = True
    invalidated: bool = False

    @model_validator(mode="after")
    def validate_times(self) -> RestaurantFactEvidence:
        values = (self.observed_at, self.effective_at, self.expires_at)
        if any(value is not None and value.tzinfo is None for value in values):
            raise ValueError("Evidence timestamps must be timezone-aware")
        if self.effective_at is not None and self.expires_at is not None:
            if self.expires_at <= self.effective_at:
                raise ValueError("expires_at must be later than effective_at")
        return self


class RestaurantQuestionEvaluation(RestaurantAnswerModel):
    question_key: str
    question: str
    entity_type: RestaurantEntityType
    entity_id: UUID
    state: AnswerState
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[UUID, ...] = ()
    fact_keys: tuple[str, ...] = ()
    evaluated_at: datetime


class RestaurantAnswerRunSnapshot(RestaurantAnswerModel):
    contract_version: Literal["restaurant-answer-evaluation/v1"] = (
        RESTAURANT_ANSWER_CONTRACT_VERSION
    )
    suite_key: str
    suite_version: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_type: RestaurantEntityType
    entity_id: UUID
    evaluated_at: datetime
    results: tuple[RestaurantQuestionEvaluation, ...]
    state_counts: dict[AnswerState, int]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExternalCitationObservation(RestaurantAnswerModel):
    provider: str = Field(min_length=1, max_length=100)
    model_or_surface: str = Field(min_length=1, max_length=200)
    locale: str = Field(min_length=2, max_length=50)
    exact_query: str = Field(min_length=1, max_length=2_000)
    observed_at: datetime
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cited_urls: tuple[str, ...] = Field(default=(), max_length=100)
    accuracy_state: ExternalAccuracyState
    verified_fact_keys: tuple[str, ...] = Field(default=(), max_length=100)
    notes: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_observation(self) -> ExternalCitationObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.accuracy_state == "accurate" and not self.verified_fact_keys:
            raise ValueError("Accurate observations require verified fact keys")
        return self
