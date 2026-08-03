from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit

from catora_api.local_profiles.models import (
    BranchProfileMatch,
    LocalAddress,
    LocalProfileConflict,
    LocalProfileObservation,
    ProfileCompleteness,
    ProfileMatchState,
    RestaurantLocationIdentity,
)

_REQUIRED_COMPLETENESS_FIELDS = (
    "title",
    "address",
    "phone",
    "categories",
    "regular_hours",
    "website_url",
    "menu_url",
    "ordering_url",
    "service_areas",
    "media",
    "attributes",
)
_WORD = re.compile(r"[^a-z0-9]+")
ConflictSeverity = Literal["critical", "high", "medium", "low"]


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _WORD.sub(" ", normalized).strip()


def normalize_phone(value: str | None) -> str:
    if value is None:
        return ""
    digits = "".join(character for character in value if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_address(value: LocalAddress) -> str:
    parts = (
        *value.address_lines,
        value.locality or "",
        value.administrative_area or "",
        value.postal_code or "",
        value.country_code or "",
    )
    return normalize_text(" ".join(part for part in parts if part))


def profile_completeness(observation: LocalProfileObservation) -> ProfileCompleteness:
    values: dict[str, object] = {
        "title": observation.title,
        "address": normalize_address(observation.address),
        "phone": normalize_phone(observation.phone),
        "categories": observation.categories,
        "regular_hours": observation.regular_hours,
        "website_url": observation.website_url,
        "menu_url": observation.menu_url,
        "ordering_url": observation.ordering_url,
        "service_areas": observation.service_areas,
        "media": observation.media_count,
        "attributes": observation.attributes,
    }
    present = tuple(
        key
        for key in _REQUIRED_COMPLETENESS_FIELDS
        if _present(values[key], field_key=key)
    )
    missing = tuple(key for key in _REQUIRED_COMPLETENESS_FIELDS if key not in present)
    score = len(present) * 10_000 // len(_REQUIRED_COMPLETENESS_FIELDS)
    return ProfileCompleteness(
        score_basis_points=score,
        present_fields=present,
        missing_fields=missing,
    )


def match_profile_to_locations(
    observation: LocalProfileObservation,
    locations: tuple[RestaurantLocationIdentity, ...],
) -> BranchProfileMatch:
    profile_name = normalize_text(observation.title)
    profile_phone = normalize_phone(observation.phone)
    profile_address = normalize_address(observation.address)
    profile_host = _hostname(observation.website_url)
    scored: list[tuple[int, str, RestaurantLocationIdentity, dict[str, object]]] = []
    for location in locations:
        name = normalize_text(location.name)
        aliases = {normalize_text(alias) for alias in location.aliases}
        phone = normalize_phone(location.phone)
        address = normalize_address(location.address)
        host = _hostname(location.website_url)
        name_exact = bool(profile_name and profile_name == name)
        alias_exact = bool(profile_name and profile_name in aliases)
        phone_exact = bool(profile_phone and profile_phone == phone)
        address_exact = bool(profile_address and profile_address == address)
        host_exact = bool(profile_host and profile_host == host)
        if name_exact and phone_exact and address_exact:
            score, method = 10_000, "name_phone_address"
        elif alias_exact and phone_exact and address_exact:
            score, method = 9_900, "alias_phone_address"
        elif name_exact and address_exact:
            score, method = 9_600, "name_address"
        elif alias_exact and address_exact:
            score, method = 9_400, "alias_address"
        elif name_exact and phone_exact:
            score, method = 9_200, "name_phone"
        elif alias_exact and phone_exact:
            score, method = 9_000, "alias_phone"
        elif address_exact and phone_exact:
            score, method = 8_800, "address_phone"
        elif name_exact and host_exact:
            score, method = 8_500, "name_website"
        else:
            continue
        scored.append(
            (
                score,
                method,
                location,
                {
                    "name_exact": name_exact,
                    "alias_exact": alias_exact,
                    "phone_exact": phone_exact,
                    "address_exact": address_exact,
                    "website_host_exact": host_exact,
                },
            )
        )
    scored.sort(key=lambda item: (-item[0], str(item[2].location_id)))
    if not scored:
        return BranchProfileMatch(
            external_profile_id=observation.external_profile_id,
            location_id=None,
            state="unmatched",
            method="no_supported_identity_match",
            confidence_basis_points=0,
            evidence={},
        )
    best_score = scored[0][0]
    best = [item for item in scored if item[0] == best_score]
    if len(best) > 1:
        return BranchProfileMatch(
            external_profile_id=observation.external_profile_id,
            location_id=None,
            state="ambiguous",
            method=best[0][1],
            confidence_basis_points=best_score,
            evidence={"candidate_count": len(best)},
            candidate_location_ids=tuple(item[2].location_id for item in best),
        )
    score, method, location, evidence = best[0]
    state: ProfileMatchState = "alias" if method.startswith("alias") else "exact"
    return BranchProfileMatch(
        external_profile_id=observation.external_profile_id,
        location_id=location.location_id,
        state=state,
        method=method,
        confidence_basis_points=score,
        evidence={key: bool(value) for key, value in evidence.items()},
    )


def evaluate_profile_conflicts(
    observation: LocalProfileObservation,
    location: RestaurantLocationIdentity,
) -> tuple[LocalProfileConflict, ...]:
    candidates: tuple[tuple[str, str, str, ConflictSeverity], ...] = (
        (
            "name",
            normalize_text(location.name),
            normalize_text(observation.title),
            "high",
        ),
        (
            "phone",
            normalize_phone(location.phone),
            normalize_phone(observation.phone),
            "high",
        ),
        (
            "address",
            normalize_address(location.address),
            normalize_address(observation.address),
            "critical",
        ),
        (
            "website_url",
            _normalized_url(location.website_url),
            _normalized_url(observation.website_url),
            "medium",
        ),
    )
    conflicts: list[LocalProfileConflict] = []
    for field_key, restaurant_value, provider_value, severity in candidates:
        if not restaurant_value or not provider_value or restaurant_value == provider_value:
            continue
        fingerprint = canonical_hash(
            {
                "profile": observation.external_profile_id,
                "location": str(location.location_id),
                "field": field_key,
                "restaurant": restaurant_value,
                "provider": provider_value,
            }
        )
        conflicts.append(
            LocalProfileConflict(
                field_key=field_key,
                severity=severity,
                restaurant_value=restaurant_value,
                provider_value=provider_value,
                fingerprint=fingerprint,
                explanation=(
                    f"Local profile {field_key} differs from the approved restaurant "
                    "location evidence. Human review is required before any provider action."
                ),
            )
        )
    return tuple(
        sorted(conflicts, key=lambda conflict: (conflict.field_key, conflict.fingerprint))
    )


def reconcile_profile_inventory(
    observations: Iterable[LocalProfileObservation],
    locations: tuple[RestaurantLocationIdentity, ...],
) -> dict[str, int]:
    counts = {
        "profiles": 0,
        "exact": 0,
        "alias": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "rejected": 0,
        "linked_locations": 0,
        "unlinked_locations": 0,
    }
    linked: set[object] = set()
    for observation in observations:
        counts["profiles"] += 1
        match = match_profile_to_locations(observation, locations)
        counts[match.state] += 1
        if match.location_id is not None:
            linked.add(match.location_id)
    counts["linked_locations"] = len(linked)
    counts["unlinked_locations"] = len(locations) - len(linked)
    return counts


def _present(value: object, *, field_key: str) -> bool:
    if field_key == "media":
        return isinstance(value, int) and value > 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict):
        return bool(value)
    return value is not None


def _hostname(value: str | None) -> str:
    if value is None:
        return ""
    try:
        return (urlsplit(value).hostname or "").casefold()
    except ValueError:
        return ""


def _normalized_url(value: str | None) -> str:
    if value is None:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.casefold()}://{host}{path}"
