from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

LOCAL_PROFILE_CONTRACT_VERSION: Literal["local-profile-intelligence/v1"] = (
    "local-profile-intelligence/v1"
)

LocalProvider = Literal["google_business_profile", "synthetic"]
CapabilityState = Literal[
    "documented",
    "granted",
    "tested",
    "unavailable",
    "prohibited",
]
ProfileMatchState = Literal["exact", "alias", "ambiguous", "unmatched", "rejected"]
_MANAGED_CREDENTIAL_PREFIXES = ("env:", "vault:", "secret:", "synthetic:")


class LocalProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderCapability(LocalProfileModel):
    operation: str = Field(min_length=1, max_length=160)
    state: CapabilityState
    read_only: bool = True
    scope: str | None = Field(default=None, max_length=500)
    evidence_url: str | None = Field(default=None, max_length=2_000)
    tested_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def validate_capability(self) -> ProviderCapability:
        if self.state == "tested" and self.tested_at is None:
            raise ValueError("Tested provider capabilities require tested_at")
        if not self.read_only and self.state not in {"unavailable", "prohibited"}:
            raise ValueError("Local profile mutations are unavailable in this contract")
        return self


class LocalProviderAccount(LocalProfileModel):
    provider: LocalProvider
    external_account_id: str = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, max_length=500)
    credential_reference: str = Field(min_length=1, max_length=500)
    capabilities: tuple[ProviderCapability, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_operations(self) -> LocalProviderAccount:
        operations = [capability.operation for capability in self.capabilities]
        if len(operations) != len(set(operations)):
            raise ValueError("Provider capability operations must be unique")
        if not self.credential_reference.startswith(_MANAGED_CREDENTIAL_PREFIXES):
            raise ValueError(
                "credential_reference must use env:, vault:, secret:, or synthetic:"
            )
        if self.provider == "google_business_profile" and any(
            capability.state in {"granted", "tested"}
            for capability in self.capabilities
        ):
            raise ValueError(
                "Google Business Profile capabilities cannot be granted or tested "
                "until a live adapter and account acceptance are implemented"
            )
        return self


class LocalAddress(LocalProfileModel):
    address_lines: tuple[str, ...] = Field(default=(), max_length=10)
    locality: str | None = Field(default=None, max_length=200)
    administrative_area: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=50)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class LocalHoursPeriod(LocalProfileModel):
    day: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    opens: str
    closes: str


class LocalSpecialHours(LocalProfileModel):
    starts_at: datetime
    ends_at: datetime
    opens: str | None = None
    closes: str | None = None
    closed: bool = False


class LocalProfileObservation(LocalProfileModel):
    contract_version: Literal["local-profile-intelligence/v1"] = (
        LOCAL_PROFILE_CONTRACT_VERSION
    )
    external_profile_id: str = Field(min_length=1, max_length=500)
    provider_location_name: str | None = Field(default=None, max_length=1_000)
    profile_state: Literal[
        "verified",
        "unverified",
        "suspended",
        "disabled",
        "unknown",
    ]
    title: str = Field(min_length=1, max_length=500)
    phone: str | None = Field(default=None, max_length=100)
    website_url: str | None = Field(default=None, max_length=2_000)
    menu_url: str | None = Field(default=None, max_length=2_000)
    ordering_url: str | None = Field(default=None, max_length=2_000)
    address: LocalAddress = Field(default_factory=LocalAddress)
    latitude: Decimal | None = Field(
        default=None,
        ge=Decimal("-90"),
        le=Decimal("90"),
    )
    longitude: Decimal | None = Field(
        default=None,
        ge=Decimal("-180"),
        le=Decimal("180"),
    )
    regular_hours: tuple[LocalHoursPeriod, ...] = ()
    special_hours: tuple[LocalSpecialHours, ...] = ()
    categories: tuple[str, ...] = Field(default=(), max_length=100)
    attributes: dict[str, str | bool | int | float | list[str]] = Field(
        default_factory=dict
    )
    service_areas: tuple[dict[str, str], ...] = Field(default=(), max_length=500)
    media_count: int = Field(default=0, ge=0)
    observed_at: datetime
    source_updated_at: datetime | None = None
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observation(self) -> LocalProfileObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("Profile observed_at must be timezone-aware")
        if self.source_updated_at is not None and self.source_updated_at.tzinfo is None:
            raise ValueError("Profile source_updated_at must be timezone-aware")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        return self


class RestaurantLocationIdentity(LocalProfileModel):
    location_id: UUID
    canonical_key: str
    external_location_id: str | None = None
    name: str
    aliases: tuple[str, ...] = ()
    phone: str | None = None
    address: LocalAddress = Field(default_factory=LocalAddress)
    website_url: str | None = None


class BranchProfileMatch(LocalProfileModel):
    external_profile_id: str
    location_id: UUID | None
    state: ProfileMatchState
    method: str
    confidence_basis_points: int = Field(ge=0, le=10_000)
    evidence: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)
    candidate_location_ids: tuple[UUID, ...] = ()


class ProfileCompleteness(LocalProfileModel):
    score_basis_points: int = Field(ge=0, le=10_000)
    present_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    unavailable_fields: tuple[str, ...] = ()


class LocalProfileConflict(LocalProfileModel):
    field_key: str
    severity: Literal["critical", "high", "medium", "low"]
    restaurant_value: str | int | float | bool | list[str] | dict[str, str] | None
    provider_value: str | int | float | bool | list[str] | dict[str, str] | None
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    explanation: str
