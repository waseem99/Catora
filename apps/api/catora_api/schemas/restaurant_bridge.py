from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from catora_api.schemas.catalog_bridge import CATALOG_BRIDGE_PROTOCOL_VERSION

RESTAURANT_BRIDGE_PROFILE = "restaurant/v1"
RESTAURANT_BRIDGE_MAX_BATCH_RECORDS = 50

_FORBIDDEN_FIELD_TOKENS = frozenset(
    {
        "cart",
        "carts",
        "customer",
        "customers",
        "deliveryperson",
        "driver",
        "drivers",
        "loyalty",
        "order",
        "orders",
        "password",
        "passwords",
        "payment",
        "payments",
        "refund",
        "refunds",
        "rider",
        "riders",
        "session",
        "sessions",
        "token",
        "tokens",
    }
)

RestaurantBridgeJsonValue: TypeAlias = (
    dict[str, Any] | list[Any] | str | int | float | bool | None
)


def _contains_forbidden_field_token(value: str) -> bool:
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value).lower()
    return any(token in _FORBIDDEN_FIELD_TOKENS for token in re.split(r"[_\-.]+", normalized))


def validate_restaurant_bridge_value(
    value: RestaurantBridgeJsonValue,
    *,
    depth: int = 0,
) -> RestaurantBridgeJsonValue:
    if depth > 8:
        raise ValueError("Restaurant bridge data cannot exceed 8 nested levels")
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError("Restaurant bridge objects cannot exceed 500 fields")
        for key, item in value.items():
            if not key or len(key) > 160 or _contains_forbidden_field_token(key):
                raise ValueError(f"Restaurant bridge field '{key}' is not allowed")
            validate_restaurant_bridge_value(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 2_000:
            raise ValueError("Restaurant bridge arrays cannot exceed 2000 items")
        for item in value:
            validate_restaurant_bridge_value(item, depth=depth + 1)
    elif isinstance(value, str) and len(value) > 100_000:
        raise ValueError("Restaurant bridge strings cannot exceed 100000 characters")
    return value


class RestaurantBridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RestaurantBridgeAddress(RestaurantBridgeModel):
    street_address: str | None = Field(default=None, alias="streetAddress", max_length=500)
    address_locality: str | None = Field(default=None, alias="addressLocality", max_length=200)
    address_region: str | None = Field(default=None, alias="addressRegion", max_length=200)
    postal_code: str | None = Field(default=None, alias="postalCode", max_length=50)
    address_country: str | None = Field(default=None, alias="addressCountry", max_length=100)


class RestaurantBridgeGeo(RestaurantBridgeModel):
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class RestaurantBridgeHours(RestaurantBridgeModel):
    day_of_week: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ] = Field(alias="dayOfWeek")
    opens: str = Field(min_length=1, max_length=20)
    closes: str = Field(min_length=1, max_length=20)


class RestaurantBridgeSpecialHours(RestaurantBridgeModel):
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    opens: str | None = Field(default=None, max_length=20)
    closes: str | None = Field(default=None, max_length=20)
    closed: bool = False

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("endsAt must be after startsAt")
        if self.closed and (self.opens is not None or self.closes is not None):
            raise ValueError("Closed special hours cannot define opening times")
        return self


class RestaurantBridgeImage(RestaurantBridgeModel):
    url: HttpUrl
    alt_text: str | None = Field(default=None, alias="altText", max_length=1_000)
    position: int = Field(default=0, ge=0, le=10_000)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RestaurantBridgeModifierOption(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    price_delta: Decimal | None = Field(default=None, alias="priceDelta")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    position: int = Field(default=0, ge=0, le=10_000)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class RestaurantBridgeModifierGroup(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    required: bool = False
    min_selections: int = Field(default=0, alias="minSelections", ge=0)
    max_selections: int = Field(default=1, alias="maxSelections", ge=0)
    position: int = Field(default=0, ge=0, le=10_000)
    options: list[RestaurantBridgeModifierOption] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_group(self) -> Self:
        if self.max_selections < self.min_selections:
            raise ValueError("maxSelections cannot be less than minSelections")
        identities = [option.id for option in self.options]
        if len(identities) != len(set(identities)):
            raise ValueError("Modifier option IDs must be unique inside a group")
        return self


class RestaurantBridgeMenuItem(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=100_000)
    price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    dietary_facts: dict[str, RestaurantBridgeJsonValue] = Field(
        default_factory=dict,
        alias="dietaryFacts",
        max_length=100,
    )
    allergen_facts: dict[str, RestaurantBridgeJsonValue] = Field(
        default_factory=dict,
        alias="allergenFacts",
        max_length=100,
    )
    images: list[RestaurantBridgeImage] = Field(default_factory=list, max_length=100)
    modifiers: list[RestaurantBridgeModifierGroup] = Field(default_factory=list, max_length=100)
    status: Literal["active", "inactive", "deleted"] = "active"
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @field_validator("dietary_facts", "allergen_facts")
    @classmethod
    def validate_facts(
        cls,
        value: dict[str, RestaurantBridgeJsonValue],
    ) -> dict[str, RestaurantBridgeJsonValue]:
        validate_restaurant_bridge_value(value)
        return value

    @model_validator(mode="after")
    def validate_item(self) -> Self:
        group_ids = [group.id for group in self.modifiers]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Modifier group IDs must be unique inside a menu item")
        if self.price is not None and self.currency is None:
            raise ValueError("Menu item currency is required when price is present")
        return self


class RestaurantBridgeMenuSection(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=20_000)
    position: int = Field(default=0, ge=0, le=10_000)
    items: list[RestaurantBridgeMenuItem] = Field(default_factory=list, max_length=5_000)

    @model_validator(mode="after")
    def validate_section(self) -> Self:
        identities = [item.id for item in self.items]
        if len(identities) != len(set(identities)):
            raise ValueError("Menu item IDs must be unique inside a section")
        return self


class RestaurantBridgeMenu(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=20_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: Literal["active", "inactive", "deleted"] = "active"
    available_from: datetime | None = Field(default=None, alias="availableFrom")
    available_until: datetime | None = Field(default=None, alias="availableUntil")
    sections: list[RestaurantBridgeMenuSection] = Field(default_factory=list, max_length=500)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @model_validator(mode="after")
    def validate_menu(self) -> Self:
        if (
            self.available_from is not None
            and self.available_until is not None
            and self.available_until <= self.available_from
        ):
            raise ValueError("availableUntil must be after availableFrom")
        identities = [section.id for section in self.sections]
        if len(identities) != len(set(identities)):
            raise ValueError("Menu section IDs must be unique inside a menu")
        return self


class RestaurantBridgeServiceArea(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    area_type: Literal[
        "city",
        "district",
        "neighborhood",
        "postal_code",
        "polygon",
        "radius",
    ] = Field(alias="areaType")
    geometry: dict[str, RestaurantBridgeJsonValue] = Field(default_factory=dict, max_length=100)
    ordering_url: HttpUrl | None = Field(default=None, alias="orderingUrl")
    status: Literal["active", "inactive", "deleted"] = "active"

    @field_validator("geometry")
    @classmethod
    def validate_geometry(
        cls,
        value: dict[str, RestaurantBridgeJsonValue],
    ) -> dict[str, RestaurantBridgeJsonValue]:
        validate_restaurant_bridge_value(value)
        return value


class RestaurantBridgeLocation(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    aliases: list[str] = Field(default_factory=list, max_length=500)
    phone: str | None = Field(default=None, max_length=100)
    website_url: HttpUrl | None = Field(default=None, alias="websiteUrl")
    ordering_url: HttpUrl | None = Field(default=None, alias="orderingUrl")
    address: RestaurantBridgeAddress = Field(default_factory=RestaurantBridgeAddress)
    geo: RestaurantBridgeGeo | None = None
    regular_hours: list[RestaurantBridgeHours] = Field(
        default_factory=list,
        alias="regularHours",
        max_length=100,
    )
    special_hours: list[RestaurantBridgeSpecialHours] = Field(
        default_factory=list,
        alias="specialHours",
        max_length=500,
    )
    service_modes: list[
        Literal["dine_in", "takeaway", "drive_through", "delivery", "curbside", "catering"]
    ] = Field(default_factory=list, alias="serviceModes", max_length=20)
    facilities: list[str] = Field(default_factory=list, max_length=200)
    cuisine_types: list[str] = Field(default_factory=list, alias="cuisineTypes", max_length=100)
    service_areas: list[RestaurantBridgeServiceArea] = Field(
        default_factory=list,
        alias="serviceAreas",
        max_length=1_000,
    )
    menus: list[RestaurantBridgeMenu] = Field(default_factory=list, max_length=100)
    status: Literal["active", "temporarily_closed", "inactive", "deleted"] = "active"
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @model_validator(mode="after")
    def validate_location(self) -> Self:
        menu_ids = [menu.id for menu in self.menus]
        if len(menu_ids) != len(set(menu_ids)):
            raise ValueError("Menu IDs must be unique inside a location")
        area_ids = [area.id for area in self.service_areas]
        if len(area_ids) != len(set(area_ids)):
            raise ValueError("Service area IDs must be unique inside a location")
        return self


class RestaurantBridgeOffer(RestaurantBridgeModel):
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=20_000)
    location_ids: list[str] = Field(default_factory=list, alias="locationIds", max_length=10_000)
    menu_item_ids: list[str] = Field(default_factory=list, alias="menuItemIds", max_length=10_000)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    status: Literal["scheduled", "active", "expired", "cancelled", "unknown"] = "unknown"
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @model_validator(mode="after")
    def validate_offer(self) -> Self:
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("endsAt must be after startsAt")
        if not self.location_ids and not self.menu_item_ids:
            raise ValueError("Offer must reference at least one location or menu item")
        return self


class RestaurantBridgeBrand(RestaurantBridgeModel):
    record_type: Literal["restaurant_brand"] = Field(alias="recordType")
    id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=1_000)
    legal_name: str | None = Field(default=None, alias="legalName", max_length=1_000)
    website_url: HttpUrl | None = Field(default=None, alias="websiteUrl")
    aliases: list[str] = Field(default_factory=list, max_length=500)
    locations: list[RestaurantBridgeLocation] = Field(min_length=1, max_length=10_000)
    offers: list[RestaurantBridgeOffer] = Field(default_factory=list, max_length=10_000)
    status: Literal["active", "inactive", "deleted"] = "active"
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @model_validator(mode="after")
    def validate_brand(self) -> Self:
        location_ids = [location.id for location in self.locations]
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("Location IDs must be unique inside a brand")
        known_locations = set(location_ids)
        item_ids = {
            item.id
            for location in self.locations
            for menu in location.menus
            for section in menu.sections
            for item in section.items
        }
        for offer in self.offers:
            if any(location_id not in known_locations for location_id in offer.location_ids):
                raise ValueError("Offer locationIds must reference locations in the same brand")
            if any(item_id not in item_ids for item_id in offer.menu_item_ids):
                raise ValueError("Offer menuItemIds must reference items in the same brand")
        return self


class RestaurantBridgeSourceCreateRequest(RestaurantBridgeModel):
    name: str = Field(min_length=2, max_length=200)


class RestaurantBridgeSourceProvisionResponse(RestaurantBridgeModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    endpoint: HttpUrl
    token: str = Field(min_length=32)
    token_fingerprint: str = Field(alias="tokenFingerprint", min_length=12, max_length=12)
    protocol_version: Literal["2026-07-bridge-v1"] = Field(alias="protocolVersion")
    profile: Literal["restaurant/v1"] = RESTAURANT_BRIDGE_PROFILE


class RestaurantBridgeSnapshotManifest(RestaurantBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    profile: Literal["restaurant/v1"]
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    started_at: datetime = Field(alias="startedAt")
    declared_brand_count: int = Field(alias="declaredBrandCount", ge=0)
    declared_location_count: int = Field(alias="declaredLocationCount", ge=0)
    declared_menu_item_count: int = Field(alias="declaredMenuItemCount", ge=0)
    source_label: str | None = Field(default=None, alias="sourceLabel", max_length=200)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=30)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class RestaurantBridgeBatch(RestaurantBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    profile: Literal["restaurant/v1"]
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    sequence: int = Field(ge=0)
    records: list[RestaurantBridgeBrand] = Field(
        min_length=1,
        max_length=RESTAURANT_BRIDGE_MAX_BATCH_RECORDS,
    )

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class RestaurantBridgeCompleteRequest(RestaurantBridgeModel):
    protocol_version: str = Field(alias="protocolVersion")
    profile: Literal["restaurant/v1"]
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    batch_count: int = Field(alias="batchCount", gt=0)
    brand_count: int = Field(alias="brandCount", ge=0)
    location_count: int = Field(alias="locationCount", ge=0)
    menu_item_count: int = Field(alias="menuItemCount", ge=0)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != CATALOG_BRIDGE_PROTOCOL_VERSION:
            raise ValueError("Unsupported catalog bridge protocol version")
        return value


class RestaurantBridgeSnapshotStatus(RestaurantBridgeModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    profile: Literal["restaurant/v1"] = RESTAURANT_BRIDGE_PROFILE
    status: Literal["receiving", "queued", "processing", "completed", "failed"]
    accepted_batches: int = Field(alias="acceptedBatches", ge=0)
    accepted_brands: int = Field(alias="acceptedBrands", ge=0)
    accepted_locations: int = Field(alias="acceptedLocations", ge=0)
    accepted_menu_items: int = Field(alias="acceptedMenuItems", ge=0)
    ingestion_job_id: uuid.UUID | None = Field(default=None, alias="ingestionJobId")
