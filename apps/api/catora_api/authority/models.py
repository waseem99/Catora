from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AUTHORITY_CONTRACT_VERSION: Literal["restaurant-authority/v1"] = "restaurant-authority/v1"

AuthorityProvider = Literal[
    "synthetic",
    "backlink_provider",
    "local_citation_provider",
    "mention_provider",
    "permitted_public_web",
]
AuthorityObservationType = Literal[
    "backlink",
    "local_citation",
    "unlinked_mention",
    "media_opportunity",
]
IdentityState = Literal["exact", "alias", "ambiguous", "unmatched"]
LinkState = Literal["current", "new", "lost", "broken", "not_applicable"]
RiskState = Literal["allowed", "review_required", "prohibited"]
OpportunityType = Literal[
    "citation_correction",
    "link_reclamation",
    "relationship_outreach",
    "expert_commentary",
    "data_story",
    "community_partnership",
    "approved_guest_contribution",
]
OpportunityState = Literal["open", "suppressed", "approved", "rejected", "closed"]
SuppressionReason = Literal[
    "do_not_contact",
    "legal_restriction",
    "provider_terms",
    "brand_policy",
    "prior_opt_out",
]
OutreachChannel = Literal["email", "contact_form", "manual_relationship"]
OutreachDecision = Literal["approved", "rejected"]
_FORBIDDEN_METRIC_KEYS = frozenset(
    {
        "user_id",
        "customer_id",
        "order_id",
        "transaction_id",
        "email",
        "phone",
        "ip",
        "session_id",
    }
)


class AuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityCapability(AuthorityModel):
    operation: str = Field(min_length=3, max_length=100)
    state: Literal["documented", "granted", "tested", "unavailable", "prohibited"]
    scope: str = Field(min_length=1, max_length=500)
    tested_at: datetime | None = None

    @model_validator(mode="after")
    def validate_tested(self) -> AuthorityCapability:
        if self.state == "tested" and self.tested_at is None:
            raise ValueError("Tested authority capability requires tested_at")
        return self


class AuthorityObservation(AuthorityModel):
    contract_version: Literal["restaurant-authority/v1"] = AUTHORITY_CONTRACT_VERSION
    provider: AuthorityProvider
    external_account_id: str = Field(min_length=1, max_length=500)
    external_observation_id: str = Field(min_length=1, max_length=500)
    observation_type: AuthorityObservationType
    brand_id: UUID | None = None
    location_id: UUID | None = None
    source_url: str = Field(min_length=1, max_length=2_000)
    target_url: str = Field(min_length=1, max_length=2_000)
    source_title: str | None = Field(default=None, max_length=500)
    anchor_or_mention_text: str | None = Field(default=None, max_length=1_000)
    provider_metrics: dict[str, int | float | str | bool] = Field(
        default_factory=dict,
        max_length=50,
    )
    identity_state: IdentityState
    identity_method: str = Field(min_length=1, max_length=100)
    link_state: LinkState = "not_applicable"
    nofollow: bool | None = None
    sponsored: bool | None = None
    observed_at: datetime
    source_updated_at: datetime | None = None
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observation(self) -> AuthorityObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.source_updated_at is not None and self.source_updated_at.tzinfo is None:
            raise ValueError("source_updated_at must be timezone-aware")
        if self.identity_state in {"exact", "alias"} and not (
            self.brand_id or self.location_id
        ):
            raise ValueError("Matched observations require a brand or location identity")
        metric_keys = {key.casefold() for key in self.provider_metrics}
        if metric_keys.intersection(_FORBIDDEN_METRIC_KEYS):
            raise ValueError("Authority provider metrics contain prohibited identifiers")
        return self


class AuthorityOpportunity(AuthorityModel):
    observation_id: UUID | None = None
    opportunity_type: OpportunityType
    state: OpportunityState = "open"
    risk_state: RiskState
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2_000)
    verification_method: str = Field(min_length=1, max_length=1_000)
    owner_role: str = Field(min_length=1, max_length=100)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=50)
    score_basis_points: int = Field(ge=0, le=10_000)
    score_version: Literal["authority-opportunity/v1"] = "authority-opportunity/v1"


class OutreachDraft(AuthorityModel):
    opportunity_id: UUID
    channel: OutreachChannel
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5_000)
    factual_claims: tuple[str, ...] = Field(max_length=20)
    evidence_hashes: tuple[str, ...] = Field(min_length=1, max_length=50)
    suppression_checked: bool
    legal_basis_confirmed: bool
    status: Literal["draft", "approved", "rejected"] = "draft"
    send_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_draft(self) -> OutreachDraft:
        if not self.suppression_checked:
            raise ValueError("Outreach drafts require suppression checking")
        if not self.legal_basis_confirmed:
            raise ValueError("Outreach drafts require a confirmed legal basis")
        return self


class SuppressionRecord(AuthorityModel):
    normalized_target: str = Field(min_length=1, max_length=500)
    reason: SuppressionReason
    effective_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_suppression(self) -> SuppressionRecord:
        if self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must be timezone-aware")
            if self.expires_at <= self.effective_at:
                raise ValueError("expires_at must be later than effective_at")
        return self
