from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MEASUREMENT_CONTRACT_VERSION: Literal["measurement-observation/v1"] = (
    "measurement-observation/v1"
)
MeasurementProvider = Literal[
    "synthetic",
    "google_search_console",
    "ga4",
    "pagespeed_insights",
    "crux",
    "bing_webmaster",
    "indexnow",
    "external_ai_search",
]
SampleState = Literal["complete", "sampled", "partial", "unavailable"]
FreshnessState = Literal["current", "stale", "disconnected", "unavailable"]
AttributionState = Literal["exact", "mapped", "ambiguous", "unmapped"]

_ALLOWED_DIMENSIONS = frozenset(
    {
        "page",
        "query",
        "country",
        "device",
        "date",
        "landing_page",
        "session_source",
        "session_medium",
        "referrer_host",
        "metric_scope",
        "locale",
        "market",
        "provider_model",
    }
)
_FORBIDDEN_DIMENSIONS = frozenset(
    {
        "user_id",
        "client_id",
        "session_id",
        "ip",
        "email",
        "phone",
        "customer_id",
        "order_id",
        "transaction_id",
        "address",
    }
)


class MeasurementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MeasurementProviderCapability(MeasurementModel):
    operation: str = Field(min_length=1, max_length=160)
    state: Literal["documented", "granted", "tested", "unavailable", "prohibited"]
    scope: str | None = Field(default=None, max_length=500)
    tested_at: datetime | None = None

    @model_validator(mode="after")
    def validate_tested(self) -> MeasurementProviderCapability:
        if self.state == "tested" and self.tested_at is None:
            raise ValueError("Tested measurement capability requires tested_at")
        return self


class MeasurementProperty(MeasurementModel):
    provider: MeasurementProvider
    external_property_id: str = Field(min_length=1, max_length=500)
    property_type: Literal["site", "web_stream", "origin", "url", "account"]
    display_name: str | None = Field(default=None, max_length=500)
    canonical_origin: str | None = Field(default=None, max_length=2_000)
    timezone: str = Field(min_length=1, max_length=100)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class MeasurementObservation(MeasurementModel):
    contract_version: Literal["measurement-observation/v1"] = (
        MEASUREMENT_CONTRACT_VERSION
    )
    provider: MeasurementProvider
    external_property_id: str = Field(min_length=1, max_length=500)
    metric_key: str = Field(min_length=1, max_length=160)
    metric_version: str = Field(min_length=1, max_length=100)
    value_microunits: int
    dimensions: dict[str, str] = Field(default_factory=dict, max_length=20)
    window_start: datetime
    window_end: datetime
    timezone: str = Field(min_length=1, max_length=100)
    sample_state: SampleState
    freshness_state: FreshnessState
    source_definition: dict[str, str | int | bool] = Field(default_factory=dict)
    observed_at: datetime
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observation(self) -> MeasurementObservation:
        for name, value in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("observed_at", self.observed_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("Measurement window_end must be after window_start")
        keys = {key.casefold() for key in self.dimensions}
        if keys.intersection(_FORBIDDEN_DIMENSIONS):
            raise ValueError("Measurement dimensions contain user or transaction identifiers")
        if not keys.issubset(_ALLOWED_DIMENSIONS):
            raise ValueError("Measurement dimensions are outside the aggregate allowlist")
        if any(len(value) > 2_000 for value in self.dimensions.values()):
            raise ValueError("Measurement dimension values are too long")
        return self


class MeasurementAttribution(MeasurementModel):
    observation_id: UUID
    target_type: Literal["brand", "location", "menu", "menu_item", "page"]
    target_id: UUID
    state: AttributionState
    method: str = Field(min_length=1, max_length=100)
    confidence_basis_points: int = Field(ge=0, le=10_000)
    evidence: dict[str, str | bool | int] = Field(default_factory=dict)


class ChangeAnnotation(MeasurementModel):
    annotation_type: Literal[
        "published_change",
        "provider_change",
        "campaign",
        "incident",
        "manual_note",
    ]
    target_type: Literal["brand", "location", "menu", "menu_item", "page"]
    target_id: UUID
    occurred_at: datetime
    source_revision: str | None = Field(default=None, max_length=100)
    details: dict[str, str | bool | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time(self) -> ChangeAnnotation:
        if self.occurred_at.tzinfo is None:
            raise ValueError("Change annotation occurred_at must be timezone-aware")
        return self


class MeasurementComparison(MeasurementModel):
    metric_key: str
    baseline_value_microunits: int
    selected_value_microunits: int
    delta_microunits: int
    baseline_window_start: datetime
    baseline_window_end: datetime
    selected_window_start: datetime
    selected_window_end: datetime
    sample_state: SampleState
    interpretation: Literal["observation_only", "correlation_only"] = "correlation_only"
    causal_claim_allowed: bool = False

    @model_validator(mode="after")
    def prohibit_causality(self) -> MeasurementComparison:
        if self.causal_claim_allowed:
            raise ValueError("Measurement comparisons cannot claim causality")
        expected = self.selected_value_microunits - self.baseline_value_microunits
        if self.delta_microunits != expected:
            raise ValueError("Measurement comparison delta does not reconcile")
        return self
