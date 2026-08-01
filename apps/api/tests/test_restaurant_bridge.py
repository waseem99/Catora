from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from catora_api.config import Settings
from catora_api.connectors.catalog_bridge import CatalogBridgeConnector
from catora_api.main import app
from catora_api.schemas.catalog_bridge import CATALOG_BRIDGE_PROTOCOL_VERSION
from catora_api.schemas.restaurant_bridge import (
    RESTAURANT_BRIDGE_PROFILE,
    RestaurantBridgeBatch,
    RestaurantBridgeBrand,
)


def _brand() -> dict[str, Any]:
    return {
        "recordType": "restaurant_brand",
        "id": "brand-1",
        "name": "North Grill",
        "locations": [
            {
                "id": "location-1",
                "name": "North Grill Lahore",
                "address": {
                    "streetAddress": "1 Main Road",
                    "addressLocality": "Lahore",
                    "addressCountry": "PK",
                },
                "serviceModes": ["dine_in", "takeaway", "delivery"],
                "menus": [
                    {
                        "id": "menu-1",
                        "name": "Main Menu",
                        "currency": "PKR",
                        "sections": [
                            {
                                "id": "section-1",
                                "name": "Burgers",
                                "items": [
                                    {
                                        "id": "item-1",
                                        "name": "Signature Burger",
                                        "price": "799.00",
                                        "currency": "PKR",
                                        "availability": "available",
                                        "dietaryFacts": {"halal": "verified"},
                                        "allergenFacts": {
                                            "contains": ["wheat", "milk"]
                                        },
                                        "modifiers": [
                                            {
                                                "id": "group-1",
                                                "name": "Cheese",
                                                "options": [
                                                    {
                                                        "id": "option-1",
                                                        "name": "Cheddar",
                                                        "priceDelta": "100.00",
                                                        "currency": "PKR",
                                                        "availability": "available",
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "offers": [
            {
                "id": "offer-1",
                "name": "Weekday Meal",
                "locationIds": ["location-1"],
                "status": "active",
            }
        ],
    }


def test_restaurant_bridge_requires_both_foundation_flags() -> None:
    assert Settings().catalog_bridge_enabled is False
    assert Settings().restaurant_domain_enabled is False


def test_restaurant_bridge_allows_public_location_addresses() -> None:
    parsed = RestaurantBridgeBrand.model_validate(_brand())
    assert parsed.locations[0].address.address_locality == "Lahore"


@pytest.mark.parametrize(
    "restricted",
    [
        {"customerToken": "secret"},
        {"orders": [{"id": "order-1"}]},
        {"payment": {"card": "not-allowed"}},
        {"loyaltySession": "not-allowed"},
    ],
)
def test_restaurant_bridge_rejects_restricted_nested_facts(
    restricted: dict[str, Any],
) -> None:
    payload = _brand()
    payload["locations"][0]["menus"][0]["sections"][0]["items"][0][
        "dietaryFacts"
    ] = restricted
    with pytest.raises(ValidationError):
        RestaurantBridgeBrand.model_validate(payload)


def test_restaurant_bridge_rejects_offer_references_outside_brand() -> None:
    payload = _brand()
    payload["offers"][0]["locationIds"] = ["unknown-location"]
    with pytest.raises(ValidationError, match="same brand"):
        RestaurantBridgeBrand.model_validate(payload)


class _MemoryStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def get_bytes(self, key: str) -> bytes:
        assert key == "bridge/restaurant-batch.json"
        return self.content


@pytest.mark.asyncio
async def test_catalog_bridge_connector_emits_restaurant_profile_records() -> None:
    snapshot_id = uuid.uuid4()
    payload = {
        "protocolVersion": CATALOG_BRIDGE_PROTOCOL_VERSION,
        "profile": RESTAURANT_BRIDGE_PROFILE,
        "snapshotId": str(snapshot_id),
        "sequence": 0,
        "records": [_brand()],
    }
    batch = RestaurantBridgeBatch.model_validate(payload)
    content = json.dumps(
        batch.model_dump(mode="json", by_alias=True),
        separators=(",", ":"),
    ).encode()
    connector = CatalogBridgeConnector(
        config={
            "profile": RESTAURANT_BRIDGE_PROFILE,
            "bridge_snapshot": {
                "protocol_version": CATALOG_BRIDGE_PROTOCOL_VERSION,
                "profile": RESTAURANT_BRIDGE_PROFILE,
                "status": "complete",
                "batches": [
                    {
                        "sequence": 0,
                        "object_key": "bridge/restaurant-batch.json",
                        "checksum": hashlib.sha256(content).hexdigest(),
                    }
                ],
            },
        },
        storage=_MemoryStorage(content),  # type: ignore[arg-type]
    )

    pages = [page async for page in connector.pages()]

    assert len(pages) == 1
    assert pages[0].records[0].record_type == "restaurant_brand"
    assert pages[0].records[0].external_id == "brand-1"
    assert pages[0].records[0].payload["locations"][0]["name"] == (
        "North Grill Lahore"
    )
    assert pages[0].next_checkpoint == {"batch_sequence": 1}


def test_restaurant_bridge_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/workspaces/{workspace_id}/restaurant-bridge/sources" in paths
    assert "/api/v1/restaurant-bridge/sources/{source_id}/snapshots" in paths
    assert (
        "/api/v1/restaurant-bridge/sources/{source_id}/snapshots/"
        "{snapshot_id}/batches/{sequence}"
    ) in paths
