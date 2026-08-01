from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RESTAURANT_DOMAIN_VERSION: Literal["restaurant-domain/v1"] = "restaurant-domain/v1"

FactState = Literal[
    "supported",
    "partial",
    "unsupported",
    "stale",
    "conflicting",
    "inaccessible",
]
Confidence = Literal["high", "medium", "low"]
AvailabilityState = Literal[
    "available",
    "unavailable",
    "unknown",
    "not_applicable",
    "conflicting",
    "stale",
]
ServiceMode = Literal[
    "dine_in",
    "takeaway",
    "drive_through",
    "delivery",
    "curbside",
    "catering",
]
RestaurantJsonValue: TypeAlias = (
    dict[str, object] | list[object] | str | int | float | bool | None
)


class RestaurantModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Address(RestaurantModel):
    street_address: str | None = None
    address_locality: str | None = None
    address_region: str | None = None
    postal_code: str | None = None
    address_country: str | None = None


class GeoCoordinates(RestaurantModel):
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class OpeningHoursInterval(RestaurantModel):
    day_of_week: Literal[
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


class SpecialHoursInterval(RestaurantModel):
    starts_at: datetime
    ends_at: datetime
    opens: str | None = None
    closes: str | None = None
    closed: bool = False

    @model_validator(mode="after")
    def validate_interval(self) -> SpecialHoursInterval:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.closed and (self.opens is not None or self.closes is not None):
            raise ValueError("closed special hours cannot also define opening times")
        return self


class RestaurantFact(RestaurantModel):
    key: str = Field(min_length=1, max_length=160)
    value: RestaurantJsonValue = None
    value_type: str = Field(min_length=1, max_length=50)
    state: FactState
    confidence: Confidence = "high"
    source_record_id: UUID
    field_path: str = Field(min_length=1, max_length=500)
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    invalidated_at: datetime | None = None
    unit: str | None = Field(default=None, max_length=30)
    locale: str | None = Field(default=None, max_length=35)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_fact(self) -> RestaurantFact:
        if self.state == "supported" and self.value is None:
            raise ValueError("supported facts require a value")
        if self.expires_at is not None and self.expires_at < self.observed_at:
            raise ValueError("expires_at cannot precede observed_at")
        if self.invalidated_at is not None and self.invalidated_at < self.observed_at:
            raise ValueError("invalidated_at cannot precede observed_at")
        return self


class FreshnessPolicy(RestaurantModel):
    entity_type: Literal[
        "brand",
        "location",
        "service_area",
        "menu",
        "menu_item",
        "offer",
    ]
    fact_key: str = Field(min_length=1, max_length=160)
    warning_age_seconds: int = Field(ge=0)
    max_age_seconds: int = Field(gt=0)
    policy_version: str = Field(min_length=1, max_length=100)
    rationale: str | None = None

    @model_validator(mode="after")
    def validate_ages(self) -> FreshnessPolicy:
        if self.max_age_seconds <= self.warning_age_seconds:
            raise ValueError("max_age_seconds must exceed warning_age_seconds")
        return self


class IdentityAlias(RestaurantModel):
    alias: str = Field(min_length=1, max_length=500)
    normalized_alias: str = Field(min_length=1, max_length=500)
    source_record_id: UUID | None = None


class ServiceArea(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    area_type: Literal[
        "city",
        "district",
        "neighborhood",
        "postal_code",
        "polygon",
        "radius",
    ]
    geometry: dict[str, object] = Field(default_factory=dict)
    ordering_url: str | None = None
    status: Literal["active", "inactive", "retired"] = "active"


class ModifierOption(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    price_delta: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability_state: Literal["available", "unavailable", "unknown", "stale"] = (
        "unknown"
    )
    position: int = Field(default=0, ge=0)


class ModifierGroup(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    required: bool = False
    min_selections: int = Field(default=0, ge=0)
    max_selections: int = Field(default=1, ge=0)
    position: int = Field(default=0, ge=0)
    options: tuple[ModifierOption, ...] = ()

    @model_validator(mode="after")
    def validate_selections(self) -> ModifierGroup:
        if self.max_selections < self.min_selections:
            raise ValueError("max_selections cannot be less than min_selections")
        keys = [option.canonical_key for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("modifier option canonical keys must be unique")
        return self


class MenuItem(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    price_amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    dietary_facts: dict[str, object] = Field(default_factory=dict)
    allergen_facts: dict[str, object] = Field(default_factory=dict)
    availability_state: AvailabilityState = "unknown"
    status: Literal["active", "inactive", "retired"] = "active"
    source_updated_at: datetime | None = None
    modifiers: tuple[ModifierGroup, ...] = ()
    facts: tuple[RestaurantFact, ...] = ()

    @model_validator(mode="after")
    def validate_item(self) -> MenuItem:
        keys = [group.canonical_key for group in self.modifiers]
        if len(keys) != len(set(keys)):
            raise ValueError("modifier group canonical keys must be unique")
        return self


class MenuSection(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    position: int = Field(default=0, ge=0)
    items: tuple[MenuItem, ...] = ()

    @model_validator(mode="after")
    def validate_items(self) -> MenuSection:
        keys = [item.canonical_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("menu item canonical keys must be unique")
        return self


class Menu(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: Literal["active", "inactive", "retired"] = "active"
    available_from: datetime | None = None
    available_until: datetime | None = None
    source_updated_at: datetime | None = None
    sections: tuple[MenuSection, ...] = ()
    facts: tuple[RestaurantFact, ...] = ()

    @model_validator(mode="after")
    def validate_menu(self) -> Menu:
        if (
            self.available_from is not None
            and self.available_until is not None
            and self.available_until <= self.available_from
        ):
            raise ValueError("available_until must be after available_from")
        keys = [section.canonical_key for section in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("menu section canonical keys must be unique")
        return self


class OfferOrPromotion(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["scheduled", "active", "expired", "cancelled", "unknown"] = (
        "unknown"
    )
    facts: tuple[RestaurantFact, ...] = ()

    @model_validator(mode="after")
    def validate_offer(self) -> OfferOrPromotion:
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("ends_at must be after starts_at")
        return self


class RestaurantLocationProjection(RestaurantModel):
    canonical_key: str = Field(min_length=1, max_length=500)
    external_location_id: str | None = None
    name: str = Field(min_length=1, max_length=500)
    phone: str | None = None
    website_url: str | None = None
    ordering_url: str | None = None
    address: Address = Field(default_factory=Address)
    geo: GeoCoordinates | None = None
    regular_hours: tuple[OpeningHoursInterval, ...] = ()
    special_hours: tuple[SpecialHoursInterval, ...] = ()
    service_modes: tuple[ServiceMode, ...] = ()
    facilities: tuple[str, ...] = ()
    cuisine_types: tuple[str, ...] = ()
    aliases: tuple[IdentityAlias, ...] = ()
    service_areas: tuple[ServiceArea, ...] = ()
    menus: tuple[Menu, ...] = ()
    offers: tuple[OfferOrPromotion, ...] = ()
    facts: tuple[RestaurantFact, ...] = ()
    status: Literal[
        "active",
        "temporarily_closed",
        "inactive",
        "retired",
    ] = "active"


class RestaurantBrandProjection(RestaurantModel):
    version: Literal["restaurant-domain/v1"] = RESTAURANT_DOMAIN_VERSION
    canonical_key: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    legal_name: str | None = None
    website_url: str | None = None
    aliases: tuple[IdentityAlias, ...] = ()
    locations: tuple[RestaurantLocationProjection, ...] = ()
    offers: tuple[OfferOrPromotion, ...] = ()
    facts: tuple[RestaurantFact, ...] = ()
    status: Literal["active", "inactive", "retired"] = "active"

    @model_validator(mode="after")
    def validate_locations(self) -> RestaurantBrandProjection:
        keys = [location.canonical_key for location in self.locations]
        if len(keys) != len(set(keys)):
            raise ValueError("location canonical keys must be unique")
        return self


class RestaurantSnapshot(RestaurantModel):
    version: Literal["restaurant-domain/v1"] = RESTAURANT_DOMAIN_VERSION
    source_id: UUID
    snapshot_id: UUID
    observed_at: datetime
    brands: tuple[RestaurantBrandProjection, ...]

    @model_validator(mode="after")
    def validate_brands(self) -> RestaurantSnapshot:
        keys = [brand.canonical_key for brand in self.brands]
        if len(keys) != len(set(keys)):
            raise ValueError("brand canonical keys must be unique")
        return self
