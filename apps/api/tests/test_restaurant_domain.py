from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from catora_api.config import Settings
from catora_api.db.base import Base
from catora_api.restaurant import (
    Address,
    FreshnessPolicy,
    GeoCoordinates,
    Menu,
    MenuItem,
    MenuSection,
    ModifierGroup,
    ModifierOption,
    OfferOrPromotion,
    OpeningHoursInterval,
    RestaurantBrandProjection,
    RestaurantFact,
    RestaurantLocationProjection,
    RestaurantSnapshot,
    SpecialHoursInterval,
    current_supported_facts,
    effective_fact_state,
    restaurant_json_ld,
    snapshot_projection_hash,
    stable_canonical_key,
)

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _fact(
    key: str,
    value: object,
    *,
    observed_at: datetime = OBSERVED_AT,
    state: str = "supported",
    expires_at: datetime | None = None,
    invalidated_at: datetime | None = None,
) -> RestaurantFact:
    return RestaurantFact(
        key=key,
        value=value,
        value_type="string",
        state=state,
        source_record_id=str(uuid.uuid4()),
        field_path=f"$.{key}",
        observed_at=observed_at,
        expires_at=expires_at,
        invalidated_at=invalidated_at,
        checksum="a" * 64,
    )


def _brand(name: str, city: str) -> RestaurantBrandProjection:
    brand_key = stable_canonical_key("brand", name)
    location_key = stable_canonical_key("location", name, city)
    menu_key = stable_canonical_key("menu", name, city, "main")
    item_key = stable_canonical_key("menu-item", name, city, "signature-burger")
    group_key = stable_canonical_key("modifier-group", item_key, "cheese")
    option_key = stable_canonical_key("modifier-option", group_key, "cheddar")
    menu = Menu(
        canonical_key=menu_key,
        name="Main Menu",
        currency="PKR",
        sections=(
            MenuSection(
                canonical_key=stable_canonical_key("menu-section", menu_key, "burgers"),
                name="Burgers",
                position=1,
                items=(
                    MenuItem(
                        canonical_key=item_key,
                        name="Signature Burger",
                        description="Beef burger with approved menu facts.",
                        price_amount=Decimal("799.00"),
                        currency="PKR",
                        availability_state="available",
                        dietary_facts={"halal": "verified"},
                        allergen_facts={"contains": ["wheat", "milk"]},
                        modifiers=(
                            ModifierGroup(
                                canonical_key=group_key,
                                name="Cheese",
                                max_selections=1,
                                options=(
                                    ModifierOption(
                                        canonical_key=option_key,
                                        name="Cheddar",
                                        price_delta=Decimal("100.00"),
                                        currency="PKR",
                                        availability_state="available",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    location = RestaurantLocationProjection(
        canonical_key=location_key,
        external_location_id=f"{city.casefold()}-01",
        name=f"{name} {city}",
        phone="+92-300-0000000",
        website_url=f"https://example.test/{city.casefold()}",
        ordering_url=f"https://order.example.test/{city.casefold()}",
        address=Address(
            street_address="1 Main Road",
            address_locality=city,
            address_country="PK",
        ),
        geo=GeoCoordinates(latitude=Decimal("31.5204"), longitude=Decimal("74.3587")),
        regular_hours=(
            OpeningHoursInterval(
                day_of_week="monday",
                opens="11:00",
                closes="23:00",
            ),
        ),
        special_hours=(
            SpecialHoursInterval(
                starts_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
                ends_at=datetime(2026, 8, 15, 0, 0, tzinfo=UTC),
                closed=True,
            ),
        ),
        service_modes=("dine_in", "takeaway", "delivery"),
        facilities=("parking", "family_seating"),
        cuisine_types=("Burgers", "Fast Food"),
        menus=(menu,),
        offers=(
            OfferOrPromotion(
                canonical_key=stable_canonical_key("offer", location_key, "weekday-meal"),
                name="Weekday Meal",
                starts_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                ends_at=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
                status="active",
            ),
        ),
    )
    return RestaurantBrandProjection(
        canonical_key=brand_key,
        name=name,
        website_url="https://example.test",
        locations=(location,),
    )


def test_restaurant_models_register_additive_tables() -> None:
    expected = {
        "restaurant_brands",
        "restaurant_locations",
        "restaurant_identity_aliases",
        "restaurant_service_areas",
        "restaurant_menus",
        "restaurant_menu_sections",
        "restaurant_menu_items",
        "restaurant_modifier_groups",
        "restaurant_modifier_options",
        "restaurant_offers_promotions",
        "restaurant_freshness_policies",
        "restaurant_fact_observations",
    }
    assert expected.issubset(Base.metadata.tables)
    assert "products" in Base.metadata.tables
    assert "catalog_sources" in Base.metadata.tables


def test_restaurant_feature_flag_is_default_off() -> None:
    assert Settings().restaurant_domain_enabled is False


def test_canonical_keys_are_unicode_normalized_and_source_independent() -> None:
    first = stable_canonical_key("Location", "Café One", "Lahore")
    second = stable_canonical_key(" location ", "Cafe\u0301 One", " lahore ")
    assert first == second
    assert first.startswith("location:")


def test_fact_freshness_and_invalidation_fail_closed() -> None:
    policy = FreshnessPolicy(
        entity_type="location",
        fact_key="regular_hours",
        warning_age_seconds=3_600,
        max_age_seconds=7_200,
        policy_version="hours/v1",
    )
    current = _fact("regular_hours", {"monday": ["11:00", "23:00"]})
    assert (
        effective_fact_state(
            current,
            policy=policy,
            as_of=OBSERVED_AT + timedelta(hours=1),
        )
        == "supported"
    )
    assert (
        effective_fact_state(
            current,
            policy=policy,
            as_of=OBSERVED_AT + timedelta(hours=3),
        )
        == "stale"
    )
    invalidated = _fact(
        "regular_hours",
        {"monday": ["11:00", "23:00"]},
        invalidated_at=OBSERVED_AT + timedelta(minutes=30),
    )
    assert (
        effective_fact_state(
            invalidated,
            policy=policy,
            as_of=OBSERVED_AT + timedelta(hours=1),
        )
        == "unsupported"
    )


def test_current_supported_facts_excludes_stale_and_conflicting_values() -> None:
    policy = FreshnessPolicy(
        entity_type="menu_item",
        fact_key="price",
        warning_age_seconds=3_600,
        max_age_seconds=7_200,
        policy_version="price/v1",
    )
    older = _fact("price", "699", observed_at=OBSERVED_AT - timedelta(minutes=30))
    newer = _fact("price", "799", observed_at=OBSERVED_AT)
    conflict = _fact("halal", "unknown", state="conflicting")
    selected = current_supported_facts(
        (conflict, newer, older),
        policies={"price": policy},
        as_of=OBSERVED_AT + timedelta(hours=1),
    )
    assert selected == {"price": newer}


def test_snapshot_hash_is_stable_across_input_order() -> None:
    first_brand = _brand("North Grill", "Lahore")
    second_brand = _brand("South Grill", "Karachi")
    first = RestaurantSnapshot(
        source_id=str(uuid.uuid4()),
        snapshot_id=str(uuid.uuid4()),
        observed_at=OBSERVED_AT,
        brands=(first_brand, second_brand),
    )
    second = RestaurantSnapshot(
        source_id=first.source_id,
        snapshot_id=first.snapshot_id,
        observed_at=first.observed_at,
        brands=(second_brand, first_brand),
    )
    assert snapshot_projection_hash(first) == snapshot_projection_hash(second)


def test_json_ld_contains_only_active_projected_entities() -> None:
    brand = _brand("North Grill", "Lahore")
    payload = restaurant_json_ld(brand)
    assert payload["@type"] == "Organization"
    locations = payload["subOrganization"]
    assert isinstance(locations, list)
    assert locations[0]["@type"] == "Restaurant"
    assert locations[0]["hasMenu"][0]["hasMenuSection"][0]["hasMenuItem"][0][
        "name"
    ] == "Signature Burger"


def test_supported_fact_without_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="supported facts require a value"):
        _fact("halal", None)


def test_duplicate_location_and_modifier_keys_are_rejected() -> None:
    brand = _brand("North Grill", "Lahore")
    with pytest.raises(ValidationError, match="location canonical keys must be unique"):
        RestaurantBrandProjection(
            canonical_key=brand.canonical_key,
            name=brand.name,
            locations=(brand.locations[0], brand.locations[0]),
        )
    option = ModifierOption(canonical_key="option:one", name="One")
    with pytest.raises(
        ValidationError,
        match="modifier option canonical keys must be unique",
    ):
        ModifierGroup(
            canonical_key="group:one",
            name="Options",
            options=(option, option),
        )
