from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from catora_api.connectors.shopify import (
    SHOPIFY_API_VERSION,
    ShopifyCatalogConnector,
    ShopifyConnectorConfig,
)
from catora_api.secrets import SecretValue

TOKEN = "shpat_super_secret_value"


def product_node(product_id: str, updated_at: str = "2026-07-20T10:00:00Z") -> dict[str, Any]:
    return {
        "id": product_id,
        "legacyResourceId": "101",
        "title": "Cloud Sofa",
        "handle": "cloud-sofa",
        "descriptionHtml": "<p>Three-seat sofa</p>",
        "vendor": "Catora Demo",
        "productType": "Sofa",
        "status": "ACTIVE",
        "tags": ["living-room"],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": updated_at,
        "publishedAt": "2026-01-02T00:00:00Z",
        "onlineStoreUrl": "https://example.com/products/cloud-sofa",
        "seo": {"title": "Cloud Sofa", "description": "Comfortable sofa"},
        "options": [
            {
                "id": "gid://shopify/ProductOption/1",
                "name": "Color",
                "optionValues": [{"id": "gid://shopify/ProductOptionValue/1", "name": "Blue"}],
            }
        ],
        "variants": {
            "nodes": [
                {
                    "id": "gid://shopify/ProductVariant/1",
                    "legacyResourceId": "201",
                    "title": "Blue",
                    "displayName": "Cloud Sofa - Blue",
                    "sku": "SOFA-BLUE",
                    "barcode": None,
                    "price": "1299.00",
                    "compareAtPrice": None,
                    "availableForSale": True,
                    "inventoryQuantity": 8,
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": updated_at,
                    "selectedOptions": [{"name": "Color", "value": "Blue"}],
                    "image": None,
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": "v1"},
        },
        "media": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
        "collections": {
            "nodes": [{"id": "gid://shopify/Collection/1", "title": "Sofas", "handle": "sofas", "updatedAt": updated_at}],
            "pageInfo": {"hasNextPage": False, "endCursor": "col1"},
        },
        "metafields": {
            "nodes": [
                {
                    "id": "gid://shopify/Metafield/1",
                    "namespace": "specs",
                    "key": "material",
                    "type": "single_line_text_field",
                    "value": "Boucle",
                    "updatedAt": updated_at,
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": "m1"},
        },
    }


def extensions(
    *, requested: float = 20, actual: float = 15, available: float = 900, restore: float = 50
) -> dict[str, Any]:
    return {
        "cost": {
            "requestedQueryCost": requested,
            "actualQueryCost": actual,
            "throttleStatus": {
                "maximumAvailable": 1000,
                "currentlyAvailable": available,
                "restoreRate": restore,
            },
        }
    }


def config(**overrides: Any) -> ShopifyConnectorConfig:
    values: dict[str, Any] = {
        "shop_domain": "Demo-Store.myshopify.com",
        "access_token": SecretValue(TOKEN),
    }
    values.update(overrides)
    return ShopifyConnectorConfig(**values)


@pytest.mark.asyncio
async def test_validation_uses_admin_graphql_without_exposing_token() -> None:
    captured_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return httpx.Response(
            200,
            json={
                "data": {
                    "shop": {
                        "id": "gid://shopify/Shop/1",
                        "name": "Demo",
                        "myshopifyDomain": "demo-store.myshopify.com",
                    }
                },
                "extensions": extensions(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(), client=client)
        validation = await connector.validate()

    assert validation.valid
    assert captured_headers[0]["x-shopify-access-token"] == TOKEN
    assert TOKEN not in repr(connector.config)
    assert connector.config.endpoint.endswith(f"/admin/api/{SHOPIFY_API_VERSION}/graphql.json")


@pytest.mark.asyncio
async def test_products_paginate_and_resume_from_cursor() -> None:
    observed_after: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        after = variables["after"]
        observed_after.append(after)
        if after is None:
            edge = {"cursor": "cursor-1", "node": product_node("gid://shopify/Product/1")}
            page_info = {"hasNextPage": True, "endCursor": "cursor-1"}
        else:
            edge = {"cursor": "cursor-2", "node": product_node("gid://shopify/Product/2")}
            page_info = {"hasNextPage": False, "endCursor": "cursor-2"}
        return httpx.Response(
            200,
            json={
                "data": {"products": {"edges": [edge], "pageInfo": page_info}},
                "extensions": extensions(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(), client=client)
        pages = [page async for page in connector.pages(page_size=250)]

    assert observed_after == [None, "cursor-1"]
    assert [page.records[0].external_id for page in pages] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
    ]
    assert pages[-1].next_checkpoint["cursor"] == "cursor-2"
    assert pages[0].records[0].source_updated_at == datetime(2026, 7, 20, 10, tzinfo=UTC)
    assert TOKEN not in json.dumps(pages[0].records[0].payload)


@pytest.mark.asyncio
async def test_checkpoint_starts_after_saved_cursor() -> None:
    observed_after: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed_after.append(body["variables"]["after"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {"cursor": "cursor-3", "node": product_node("gid://shopify/Product/3")}
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": "cursor-3"},
                    }
                },
                "extensions": extensions(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(), client=client)
        pages = [page async for page in connector.pages(checkpoint={"cursor": "cursor-2"})]

    assert observed_after == ["cursor-2"]
    assert pages[0].records[0].external_id == "gid://shopify/Product/3"


@pytest.mark.asyncio
async def test_incremental_query_uses_utc_timestamp() -> None:
    queries: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        queries.append(body["variables"]["query"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}
                },
                "extensions": extensions(),
            },
        )

    updated_after = datetime.fromisoformat("2026-07-01T05:00:00+05:00")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(updated_after=updated_after), client=client)
        _ = [page async for page in connector.pages()]

    assert queries == ["updated_at:>'2026-07-01T00:00:00Z'"]


@pytest.mark.asyncio
async def test_throttle_wait_is_bounded_and_recorded() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {"cursor": "cursor-1", "node": product_node("gid://shopify/Product/1")}
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": "cursor-1"},
                    }
                },
                "extensions": extensions(requested=300, available=0, restore=50),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(
            config(), client=client, sleep=sleep, max_throttle_wait_seconds=2.5
        )
        pages = [page async for page in connector.pages()]

    assert waits == [2.5]
    assert pages[0].next_checkpoint["cost"] == {
        "requested": 300.0,
        "actual": 15.0,
        "currently_available": 0.0,
        "restore_rate": 50.0,
    }


@pytest.mark.asyncio
async def test_graphql_access_error_is_sanitized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Access denied for products"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(), client=client)
        validation = await connector.validate()

    assert not validation.valid
    assert validation.errors == ("Shopify authentication or product access failed",)
    assert TOKEN not in " ".join(validation.errors)


@pytest.mark.asyncio
async def test_hash_is_deterministic_and_nested_truncation_is_flagged() -> None:
    node = product_node("gid://shopify/Product/1")
    node["variants"]["pageInfo"]["hasNextPage"] = True

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": {
                        "edges": [{"cursor": "cursor-1", "node": node}],
                        "pageInfo": {"hasNextPage": False, "endCursor": "cursor-1"},
                    }
                },
                "extensions": extensions(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyCatalogConnector(config(), client=client)
        first = [page async for page in connector.pages()]
        second = [page async for page in connector.pages()]

    assert first[0].records[0].content_hash == second[0].records[0].content_hash
    assert first[0].records[0].warnings == ("variants_truncated",)


def test_config_rejects_unsafe_domains_and_naive_incremental_dates() -> None:
    with pytest.raises(ValueError, match="myshopify"):
        config(shop_domain="https://example.com")
    with pytest.raises(ValueError, match="timezone-aware"):
        config(updated_after=datetime(2026, 7, 1))
