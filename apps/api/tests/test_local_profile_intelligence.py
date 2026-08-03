from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from catora_api.local_profiles import (
    GoogleBusinessProfileProvider,
    LocalAddress,
    LocalProfileCapabilityUnavailable,
    LocalProfileObservation,
    LocalProviderAccount,
    ProviderCapability,
    RestaurantLocationIdentity,
    evaluate_profile_conflicts,
    match_profile_to_locations,
    profile_completeness,
    reconcile_profile_inventory,
)

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _observation(**overrides: object) -> LocalProfileObservation:
    values: dict[str, object] = {
        "external_profile_id": "locations/123",
        "provider_location_name": "accounts/1/locations/123",
        "profile_state": "verified",
        "title": "North Grill Lahore",
        "phone": "+92 300 1234567",
        "website_url": "https://example.test/locations/lahore",
        "menu_url": "https://example.test/menu",
        "ordering_url": "https://order.example.test/lahore",
        "address": LocalAddress(
            address_lines=("1 Main Road",),
            locality="Lahore",
            administrative_area="Punjab",
            country_code="PK",
        ),
        "latitude": Decimal("31.5204"),
        "longitude": Decimal("74.3587"),
        "regular_hours": (),
        "special_hours": (),
        "categories": ("Restaurant", "Burger Restaurant"),
        "attributes": {"dine_in": True, "takeaway": True},
        "service_areas": ({"type": "city", "name": "Lahore"},),
        "media_count": 8,
        "observed_at": OBSERVED_AT,
        "source_updated_at": OBSERVED_AT,
        "observation_hash": hashlib.sha256(b"profile-123").hexdigest(),
    }
    values.update(overrides)
    return LocalProfileObservation(**values)  # type: ignore[arg-type]


def _location(
    *,
    location_id: uuid.UUID | None = None,
    name: str = "North Grill Lahore",
    aliases: tuple[str, ...] = (),
    phone: str = "+92 300 1234567",
    address_line: str = "1 Main Road",
) -> RestaurantLocationIdentity:
    return RestaurantLocationIdentity(
        location_id=location_id or uuid.uuid4(),
        canonical_key="restaurant-location:north-grill-lahore",
        external_location_id="location-1",
        name=name,
        aliases=aliases,
        phone=phone,
        address=LocalAddress(
            address_lines=(address_line,),
            locality="Lahore",
            administrative_area="Punjab",
            country_code="PK",
        ),
        website_url="https://example.test/locations/lahore",
    )


def test_provider_capability_matrix_rejects_unaccepted_mutation() -> None:
    with pytest.raises(ValidationError, match="mutations are unavailable"):
        ProviderCapability(
            operation="update_location",
            state="documented",
            read_only=False,
        )
    prohibited = ProviderCapability(
        operation="update_location",
        state="prohibited",
        read_only=False,
    )
    assert prohibited.state == "prohibited"


def test_profile_completeness_is_transparent_and_reconciled() -> None:
    completeness = profile_completeness(_observation())
    assert completeness.present_fields == (
        "title",
        "address",
        "phone",
        "categories",
        "website_url",
        "menu_url",
        "ordering_url",
        "service_areas",
        "media",
        "attributes",
    )
    assert completeness.missing_fields == ("regular_hours",)
    assert completeness.score_basis_points == 9_090


def test_exact_and_alias_identity_matching_are_deterministic() -> None:
    exact_location = _location()
    exact = match_profile_to_locations(_observation(), (exact_location,))
    assert exact.state == "exact"
    assert exact.location_id == exact_location.location_id
    assert exact.confidence_basis_points == 10_000

    alias_location = _location(
        name="North Grill Gulberg",
        aliases=("North Grill Lahore",),
    )
    alias = match_profile_to_locations(_observation(), (alias_location,))
    assert alias.state == "alias"
    assert alias.location_id == alias_location.location_id
    assert alias.confidence_basis_points == 9_900


def test_equal_identity_candidates_are_ambiguous_and_require_review() -> None:
    first = _location()
    second = _location()
    match = match_profile_to_locations(_observation(), (second, first))
    assert match.state == "ambiguous"
    assert match.location_id is None
    assert match.candidate_location_ids == tuple(
        sorted((first.location_id, second.location_id), key=str)
    )


def test_unmatched_profile_is_not_forced_to_a_branch() -> None:
    match = match_profile_to_locations(
        _observation(
            title="Different Restaurant",
            phone="+92 311 9999999",
            address=LocalAddress(
                address_lines=("99 Other Road",),
                locality="Karachi",
                country_code="PK",
            ),
            website_url="https://different.example.test",
        ),
        (_location(),),
    )
    assert match.state == "unmatched"
    assert match.location_id is None


def test_nap_and_website_conflicts_link_both_values() -> None:
    location = _location()
    observation = _observation(
        phone="+92 311 9999999",
        address=LocalAddress(
            address_lines=("99 Other Road",),
            locality="Lahore",
            administrative_area="Punjab",
            country_code="PK",
        ),
        website_url="https://wrong.example.test/location",
    )
    conflicts = evaluate_profile_conflicts(observation, location)
    assert {conflict.field_key for conflict in conflicts} == {
        "address",
        "phone",
        "website_url",
    }
    assert all(len(conflict.fingerprint) == 64 for conflict in conflicts)
    assert next(conflict for conflict in conflicts if conflict.field_key == "address").severity == (
        "critical"
    )


def test_inventory_reconciliation_exposes_linked_and_unlinked_totals() -> None:
    first = _location()
    second = _location(name="South Grill Lahore", phone="+92 322 1111111")
    summary = reconcile_profile_inventory((_observation(),), (first, second))
    assert summary == {
        "profiles": 1,
        "exact": 1,
        "alias": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "rejected": 0,
        "linked_locations": 1,
        "unlinked_locations": 1,
    }


@pytest.mark.asyncio
async def test_google_provider_fails_explicitly_before_account_acceptance() -> None:
    account = LocalProviderAccount(
        provider="google_business_profile",
        external_account_id="accounts/1",
        credential_reference="env:CATORA_GBP_TOKEN",
        capabilities=(
            ProviderCapability(
                operation="list_locations",
                state="documented",
                read_only=True,
            ),
        ),
    )
    provider = GoogleBusinessProfileProvider()
    with pytest.raises(LocalProfileCapabilityUnavailable):
        async for _ in provider.observations(account):
            pass


def test_local_profile_tables_register_additively() -> None:
    from catora_api.db import Base

    assert {
        "local_profile_provider_accounts",
        "local_profile_observations",
        "branch_local_profile_links",
        "local_profile_conflicts",
    }.issubset(Base.metadata.tables)
