from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from catora_api.restaurant.models import (
    FactState,
    FreshnessPolicy,
    Menu,
    MenuItem,
    RestaurantBrandProjection,
    RestaurantFact,
    RestaurantLocationProjection,
    RestaurantSnapshot,
)

_NON_WORD = re.compile(r"[^\w]+", flags=re.UNICODE)
_MULTI_DASH = re.compile(r"-+")


def normalize_identity_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = _NON_WORD.sub("-", normalized)
    return _MULTI_DASH.sub("-", normalized).strip("-")


def stable_canonical_key(namespace: str, *parts: str) -> str:
    normalized_namespace = normalize_identity_component(namespace)
    normalized_parts = [normalize_identity_component(part) for part in parts]
    if not normalized_namespace or any(not part for part in normalized_parts):
        raise ValueError("canonical key components must contain non-whitespace text")
    identity = "\x1f".join((normalized_namespace, *normalized_parts))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    readable = "-".join(normalized_parts)[:200]
    return f"{normalized_namespace}:{readable}:{digest}"


def _canonicalize(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        canonical_items = [_canonicalize(item) for item in value]
        return sorted(
            canonical_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    return value


def canonical_json(value: object) -> str:
    payload = (
        value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, BaseModel)
        else value
    )
    return json.dumps(
        _canonicalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def projection_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def effective_fact_state(
    fact: RestaurantFact,
    *,
    policy: FreshnessPolicy | None,
    as_of: datetime | None = None,
) -> FactState:
    current_time = as_of or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if fact.invalidated_at is not None and fact.invalidated_at <= current_time:
        return "unsupported"
    if fact.state in {"unsupported", "conflicting", "inaccessible", "stale"}:
        return fact.state
    if fact.expires_at is not None and fact.expires_at <= current_time:
        return "stale"
    if policy is not None:
        stale_at = fact.observed_at + timedelta(seconds=policy.max_age_seconds)
        if stale_at <= current_time:
            return "stale"
    return fact.state


def current_supported_facts(
    facts: tuple[RestaurantFact, ...],
    *,
    policies: dict[str, FreshnessPolicy],
    as_of: datetime | None = None,
) -> dict[str, RestaurantFact]:
    selected: dict[str, RestaurantFact] = {}
    for fact in sorted(
        facts,
        key=lambda item: (item.key, item.observed_at, item.checksum),
    ):
        state = effective_fact_state(
            fact,
            policy=policies.get(fact.key),
            as_of=as_of,
        )
        if state != "supported":
            continue
        previous = selected.get(fact.key)
        if previous is None or fact.observed_at >= previous.observed_at:
            selected[fact.key] = fact
    return selected


def _menu_item_json_ld(item: MenuItem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@type": "MenuItem",
        "identifier": item.canonical_key,
        "name": item.name,
    }
    if item.description:
        payload["description"] = item.description
    if item.price_amount is not None and item.currency is not None:
        offer: dict[str, Any] = {
            "@type": "Offer",
            "price": str(item.price_amount),
            "priceCurrency": item.currency.upper(),
        }
        if item.availability_state == "available":
            offer["availability"] = "https://schema.org/InStock"
        elif item.availability_state == "unavailable":
            offer["availability"] = "https://schema.org/OutOfStock"
        payload["offers"] = offer
    return payload


def _menu_json_ld(menu: Menu) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for section in sorted(menu.sections, key=lambda item: (item.position, item.canonical_key)):
        sections.append(
            {
                "@type": "MenuSection",
                "identifier": section.canonical_key,
                "name": section.name,
                "hasMenuItem": [
                    _menu_item_json_ld(item)
                    for item in sorted(section.items, key=lambda value: value.canonical_key)
                    if item.status == "active"
                ],
            }
        )
    payload: dict[str, Any] = {
        "@type": "Menu",
        "identifier": menu.canonical_key,
        "name": menu.name,
        "hasMenuSection": sections,
    }
    if menu.description:
        payload["description"] = menu.description
    return payload


def _location_address(location: RestaurantLocationProjection) -> dict[str, str]:
    address = location.address
    values = {
        "streetAddress": address.street_address,
        "addressLocality": address.address_locality,
        "addressRegion": address.address_region,
        "postalCode": address.postal_code,
        "addressCountry": address.address_country,
    }
    return {key: value for key, value in values.items() if value is not None}


def _location_json_ld(location: RestaurantLocationProjection) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@type": "Restaurant",
        "identifier": location.canonical_key,
        "name": location.name,
    }
    if location.website_url:
        payload["url"] = location.website_url
    if location.phone:
        payload["telephone"] = location.phone
    address = _location_address(location)
    if address:
        payload["address"] = {"@type": "PostalAddress", **address}
    if location.geo is not None:
        payload["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": str(location.geo.latitude),
            "longitude": str(location.geo.longitude),
        }
    if location.regular_hours:
        payload["openingHoursSpecification"] = [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": interval.day_of_week.title(),
                "opens": interval.opens,
                "closes": interval.closes,
            }
            for interval in sorted(
                location.regular_hours,
                key=lambda item: (item.day_of_week, item.opens, item.closes),
            )
        ]
    if location.cuisine_types:
        payload["servesCuisine"] = sorted(set(location.cuisine_types))
    active_menus = [menu for menu in location.menus if menu.status == "active"]
    if active_menus:
        payload["hasMenu"] = [
            _menu_json_ld(menu)
            for menu in sorted(active_menus, key=lambda item: item.canonical_key)
        ]
    return payload


def restaurant_json_ld(brand: RestaurantBrandProjection) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "identifier": brand.canonical_key,
        "name": brand.name,
    }
    if brand.legal_name:
        payload["legalName"] = brand.legal_name
    if brand.website_url:
        payload["url"] = brand.website_url
    active_locations = [location for location in brand.locations if location.status == "active"]
    if active_locations:
        payload["subOrganization"] = [
            _location_json_ld(location)
            for location in sorted(
                active_locations,
                key=lambda item: item.canonical_key,
            )
        ]
    return payload


def snapshot_projection_hash(snapshot: RestaurantSnapshot) -> str:
    return projection_hash(snapshot)
