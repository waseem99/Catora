from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from catora_api.connectors.shopify import ShopifyConnectorConfig, ShopifyConnectorError
from catora_api.connectors.shopify_bulk import ShopifyBulkCatalogConnector
from catora_api.secrets import SecretValue

SHOP_DOMAIN = "prospect-store.myshopify.com"
OPERATION_ID = "gid://shopify/BulkOperation/9001"
RESULT_URL = "https://storage.example.test/bulk-products.jsonl"


def config() -> ShopifyConnectorConfig:
    return ShopifyConnectorConfig(
        shop_domain=SHOP_DOMAIN,
        access_token=SecretValue("unit-test-token"),
    )


def product(product_id: int, title: str) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": str(product_id),
        "title": title,
        "handle": title.casefold().replace(" ", "-"),
        "descriptionHtml": f"<p>{title}</p>",
        "vendor": "Catora Demo",
        "productType": "Sofa",
        "status": "ACTIVE",
        "tags": ["living-room"],
        "createdAt": "2026-07-20T10:00:00Z",
        "updatedAt": "2026-07-24T10:00:00Z",
        "publishedAt": "2026-07-20T11:00:00Z",
        "onlineStoreUrl": f"https://example.test/products/{product_id}",
        "seo": {"title": title, "description": f"Buy {title}"},
        "options": [
            {
                "id": f"gid://shopify/ProductOption/{product_id}",
                "name": "Color",
                "optionValues": [
                    {
                        "id": f"gid://shopify/ProductOptionValue/{product_id}",
                        "name": "Sand",
                    }
                ],
            }
        ],
    }


def variant(product_id: int, variant_id: int) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/ProductVariant/{variant_id}",
        "legacyResourceId": str(variant_id),
        "title": "Sand",
        "displayName": "Sofa - Sand",
        "sku": f"SKU-{variant_id}",
        "barcode": None,
        "price": "1199.00",
        "compareAtPrice": None,
        "availableForSale": True,
        "inventoryQuantity": 4,
        "createdAt": "2026-07-20T10:00:00Z",
        "updatedAt": "2026-07-24T10:00:00Z",
        "selectedOptions": [{"name": "Color", "value": "Sand"}],
        "image": None,
        "__parentId": f"gid://shopify/Product/{product_id}",
    }


def media(product_id: int, media_id: int) -> dict[str, Any]:
    return {
        "__typename": "MediaImage",
        "id": f"gid://shopify/MediaImage/{media_id}",
        "alt": "Sofa product image",
        "image": {
            "id": f"gid://shopify/ImageSource/{media_id}",
            "url": f"https://cdn.example.test/{media_id}.png",
            "width": 1200,
            "height": 1200,
        },
        "__parentId": f"gid://shopify/Product/{product_id}",
    }


def collection(product_id: int, collection_id: int) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/Collection/{collection_id}",
        "title": "Sofas",
        "handle": "sofas",
        "updatedAt": "2026-07-24T10:00:00Z",
        "__parentId": f"gid://shopify/Product/{product_id}",
    }


def metafield(product_id: int, metafield_id: int) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/Metafield/{metafield_id}",
        "namespace": "specs",
        "key": "material",
        "type": "single_line_text_field",
        "value": "Boucle",
        "updatedAt": "2026-07-24T10:00:00Z",
        "__parentId": f"gid://shopify/Product/{product_id}",
    }


def jsonl() -> str:
    rows = [
        product(1, "Cloud Sofa"),
        variant(1, 11),
        media(1, 21),
        collection(1, 31),
        metafield(1, 41),
        product(2, "Harbor Sofa"),
        variant(2, 12),
    ]
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def operation_node(
    *,
    status: str = "COMPLETED",
    root_count: int = 2,
    result_url: str | None = RESULT_URL,
) -> dict[str, Any]:
    return {
        "id": OPERATION_ID,
        "status": status,
        "errorCode": "INTERNAL_SERVER_ERROR" if status == "FAILED" else None,
        "createdAt": "2026-07-24T10:00:00Z",
        "completedAt": (
            "2026-07-24T10:01:00Z" if status in {"COMPLETED", "FAILED"} else None
        ),
        "objectCount": 7,
        "rootObjectCount": root_count,
        "fileSize": len(jsonl()),
        "url": result_url,
        "partialDataUrl": (
            "https://storage.example.test/partial.jsonl"
            if status == "FAILED"
            else None
        ),
    }


def transport(
    *,
    status_sequence: list[str] | None = None,
    root_count: int = 2,
) -> httpx.MockTransport:
    statuses = list(status_sequence or ["COMPLETED"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == RESULT_URL
            return httpx.Response(200, text=jsonl())

        body = json.loads(request.content)
        query = body["query"]
        if "bulkOperationRunQuery" in query:
            assert body["variables"]["groupObjects"] is True
            assert "products" in body["variables"]["query"]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "bulkOperationRunQuery": {
                            "bulkOperation": {
                                "id": OPERATION_ID,
                                "status": "CREATED",
                            },
                            "userErrors": [],
                        }
                    }
                },
            )
        if "CatoraBulkOperation" in query:
            current = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "node": operation_node(
                            status=current,
                            root_count=root_count,
                            result_url=(RESULT_URL if current == "COMPLETED" else None),
                        )
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {query}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_bulk_products_stream_into_bounded_product_pages() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async with httpx.AsyncClient(
        transport=transport(status_sequence=["RUNNING", "COMPLETED"])
    ) as client:
        connector = ShopifyBulkCatalogConnector(
            config(),
            client=client,
            poll_interval_seconds=0.25,
        )
        connector._sleep = sleep
        pages = [page async for page in connector.pages(page_size=1)]

    assert waits == [0.25]
    assert len(pages) == 2
    first_product = pages[0].records[0].payload["product"]
    assert first_product["title"] == "Cloud Sofa"
    assert first_product["variants"]["nodes"][0]["sku"] == "SKU-11"
    assert first_product["media"]["nodes"][0]["image"]["width"] == 1200
    assert first_product["collections"]["nodes"][0]["title"] == "Sofas"
    assert first_product["metafields"]["nodes"][0]["value"] == "Boucle"
    assert pages[-1].next_checkpoint["operation_id"] == OPERATION_ID
    assert pages[-1].next_checkpoint["products_emitted"] == 2
    assert pages[-1].next_checkpoint["root_object_count"] == 2
    assert "url" not in pages[-1].next_checkpoint
    assert "storage.example.test" not in json.dumps(pages[-1].next_checkpoint)


@pytest.mark.asyncio
async def test_bulk_resume_reuses_operation_and_skips_persisted_products() -> None:
    submitted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted
        if request.method == "GET":
            return httpx.Response(200, text=jsonl())
        body = json.loads(request.content)
        if "bulkOperationRunQuery" in body["query"]:
            submitted = True
            raise AssertionError("Resume must not submit a new bulk operation")
        return httpx.Response(
            200,
            json={"data": {"node": operation_node()}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        connector = ShopifyBulkCatalogConnector(config(), client=client)
        pages = [
            page
            async for page in connector.pages(
                checkpoint={
                    "operation_id": OPERATION_ID,
                    "products_emitted": 1,
                }
            )
        ]

    assert not submitted
    assert [page.records[0].external_id for page in pages] == [
        "gid://shopify/Product/2"
    ]
    assert pages[0].next_checkpoint["products_emitted"] == 2


@pytest.mark.asyncio
async def test_bulk_failure_does_not_use_partial_data() -> None:
    async with httpx.AsyncClient(
        transport=transport(status_sequence=["FAILED"])
    ) as client:
        connector = ShopifyBulkCatalogConnector(config(), client=client)
        with pytest.raises(
            ShopifyConnectorError,
            match="did not complete",
        ):
            _ = [page async for page in connector.pages()]


@pytest.mark.asyncio
async def test_bulk_root_count_must_reconcile() -> None:
    async with httpx.AsyncClient(transport=transport(root_count=3)) as client:
        connector = ShopifyBulkCatalogConnector(config(), client=client)
        with pytest.raises(
            ShopifyConnectorError,
            match="count did not reconcile",
        ):
            _ = [page async for page in connector.pages()]
