from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPUTATION_CONTRACT_VERSION: Literal["reputation-intelligence/v1"] = (
    "reputation-intelligence/v1"
)
ReviewState = Literal["published", "updated", "deleted", "unavailable"]
RiskLevel = Literal["none", "low", "medium", "high", "critical"]
DraftDecision = Literal["draft", "approved", "rejected", "escalated"]


class ReputationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewProviderCapability(ReputationModel):
    operation: str = Field(min_length=1, max_length=160)
    state: Literal["documented", "granted", "tested", "unavailable", "prohibited"]
    read_only: bool = True
    tested_at: datetime | None = None

    @model_validator(mode="after")
    def validate_capability(self) -> ReviewProviderCapability:
        if self.state == "tested" and self.tested_at is None:
            raise ValueError("Tested review capabilities require tested_at")
        if not self.read_only and self.state not in {"unavailable", "prohibited"}:
            raise ValueError("Review posting is unavailable in this contract")
        return self


class ReviewProviderAccountContract(ReputationModel):
    provider: Literal["synthetic", "google", "facebook", "delivery_platform", "other"]
    external_account_id: str = Field(min_length=1, max_length=500)
    credential_reference: str = Field(min_length=1, max_length=500)
    capabilities: tuple[ReviewProviderCapability, ...] = Field(min_length=1, max_length=200)


class ReviewObservation(ReputationModel):
    contract_version: Literal["reputation-intelligence/v1"] = REPUTATION_CONTRACT_VERSION
    external_review_id: str = Field(min_length=1, max_length=500)
    external_location_id: str | None = Field(default=None, max_length=500)
    restaurant_location_id: UUID | None = None
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(default=None, max_length=20_000)
    language: str | None = Field(default=None, max_length=35)
    reviewer_display_name: str | None = Field(default=None, max_length=300)
    provider_response_text: str | None = Field(default=None, max_length=20_000)
    provider_response_updated_at: datetime | None = None
    review_created_at: datetime
    review_updated_at: datetime | None = None
    review_state: ReviewState
    observed_at: datetime
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_times(self) -> ReviewObservation:
        for name, value in (
            ("review_created_at", self.review_created_at),
            ("review_updated_at", self.review_updated_at),
            ("provider_response_updated_at", self.provider_response_updated_at),
            ("observed_at", self.observed_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        return self


class ReviewAnalysis(ReputationModel):
    analysis_version: Literal["reputation-rules/v1"] = "reputation-rules/v1"
    themes: tuple[str, ...]
    praise: tuple[str, ...]
    concerns: tuple[str, ...]
    risk_level: RiskLevel
    escalation_reasons: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewResponseDraft(ReputationModel):
    review_id: UUID
    policy_version: str = Field(min_length=1, max_length=100)
    draft_text: str = Field(min_length=1, max_length=5_000)
    evidence_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: DraftDecision = "draft"
    requires_human_approval: bool = True
    posting_allowed: bool = False

    @model_validator(mode="after")
    def enforce_governance(self) -> ReviewResponseDraft:
        if not self.requires_human_approval or self.posting_allowed:
            raise ValueError("Review drafts require human approval and cannot post")
        return self
