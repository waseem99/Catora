from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from catora_api.connectors.shopify import ShopifyConnectorConfig
from catora_api.connectors.shopify_bulk import ShopifyBulkCatalogConnector
from catora_api.db.models.catalog import CatalogSource, SourceRecord
from catora_api.normalization.adapters import normalize_source_records
from catora_api.secrets import SecretValue

PRODUCT_COUNT = 5_001
VARIANTS_PER_PRODUCT = 2
EXPECTED_SKU_COUNT = PRODUCT_COUNT * VARIANTS_PER_PRODUCT
OPERATION_ID = "gid://shopify/BulkOperation/scale-10002"
RESULT_URL = "https://storage.example.test/catora-scale.jsonl"


class SyntheticShopifyJsonl(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.rows_emitted = 0
        self.max_chunk_size = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for product_number in range(1, PRODUCT_COUNT + 1):
            product_id = f"gid://shopify/Product/{product_number}"
            product = {
                "id": product_id,
                "legacyResourceId": str(product_number),
                "title": f"Scale Product {product_number}",
                "handle": f"scale-product-{product_number}",
                "descriptionHtml": None,
                "vendor": "Catora Scale",
                "productType": "Furniture",
                "status": "ACTIVE",
                "tags": [],
                "createdAt": "2026-07-27T00:00:00Z",
                "updatedAt": "2026-07-27T00:00:00Z",
                "publishedAt": None,
                "onlineStoreUrl": None,
                "seo": {"title": None, "description": None},
                "options": [],
            }
            yield self._row(product)
            for position in range(1, VARIANTS_PER_PRODUCT + 1):
                variant_number = (product_number - 1) * VARIANTS_PER_PRODUCT + position
                variant = {
                    "id": f"gid://shopify/ProductVariant/{variant_number}",
                    "legacyResourceId": str(variant_number),
                    "title": f"Variant {position}",
                    "displayName": f"Scale Product {product_number} - Variant {position}",
                    "sku": f"SCALE-{variant_number:05d}",
                    "barcode": None,
                    "price": "100.00",
                    "compareAtPrice": None,
                    "availableForSale": True,
                    "inventoryQuantity": 1,
                    "createdAt": "2026-07-27T00:00:00Z",
                    "updatedAt": "2026-07-27T00:00:00Z",
                    "selectedOptions": [],
                    "image": None,
                    "__parentId": product_id,
                }
                yield self._row(variant)

    def _row(self, payload: dict[str, object]) -> bytes:
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        self.rows_emitted += 1
        self.max_chunk_size = max(self.max_chunk_size, len(encoded))
        return encoded


def _config() -> ShopifyConnectorConfig:
    return ShopifyConnectorConfig(
        shop_domain="scale-prospect.myshopify.com",
        access_token=SecretValue("unit-test-token"),
    )


def _transport(stream: SyntheticShopifyJsonl) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == RESULT_URL
            return httpx.Response(200, stream=stream)
        body = json.loads(request.content)
        query = body["query"]
        if "bulkOperationRunQuery" in query:
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
            return httpx.Response(
                200,
                json={
                    "data": {
                        "node": {
                            "id": OPERATION_ID,
                            "status": "COMPLETED",
                            "errorCode": None,
                            "createdAt": "2026-07-27T00:00:00Z",
                            "completedAt": "2026-07-27T00:05:00Z",
                            "objectCount": PRODUCT_COUNT * (VARIANTS_PER_PRODUCT + 1),
                            "rootObjectCount": PRODUCT_COUNT,
                            "fileSize": 0,
                            "url": RESULT_URL,
                            "partialDataUrl": None,
                        }
                    }
                },
            )
        raise AssertionError(f"Unexpected Shopify GraphQL request: {query}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_bulk_streams_more_than_10000_skus_in_bounded_pages() -> None:
    stream = SyntheticShopifyJsonl()
    product_count = 0
    variant_count = 0
    page_count = 0
    largest_page = 0
    last_checkpoint: dict[str, Any] = {}

    async with httpx.AsyncClient(transport=_transport(stream)) as client:
        connector = ShopifyBulkCatalogConnector(
            _config(),
            client=client,
            poll_interval_seconds=0,
        )
        async for page in connector.pages(page_size=250):
            page_count += 1
            largest_page = max(largest_page, len(page.records))
            product_count += len(page.records)
            for record in page.records:
                product = record.payload["product"]
                assert isinstance(product, dict)
                variants = product["variants"]
                assert isinstance(variants, dict)
                nodes = variants["nodes"]
                assert isinstance(nodes, list)
                variant_count += len(nodes)
            last_checkpoint = dict(page.next_checkpoint or {})

    assert product_count == PRODUCT_COUNT
    assert variant_count == EXPECTED_SKU_COUNT
    assert page_count == 21
    assert largest_page == 250
    assert last_checkpoint["products_emitted"] == PRODUCT_COUNT
    assert last_checkpoint["root_object_count"] == PRODUCT_COUNT
    assert "url" not in last_checkpoint
    assert RESULT_URL not in json.dumps(last_checkpoint)
    assert stream.rows_emitted == PRODUCT_COUNT * (VARIANTS_PER_PRODUCT + 1)
    assert stream.max_chunk_size < 2_048


def _source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> CatalogSource:
    return CatalogSource(
        id=source_id,
        workspace_id=workspace_id,
        storefront_id=None,
        name="Prospect Shopify",
        source_type="shopify",
        status="active",
        config={},
        credential_ref="shopify-public-installation:test",
    )


def _record(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    job_id: uuid.UUID,
) -> SourceRecord:
    return SourceRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        catalog_source_id=source_id,
        ingestion_job_id=job_id,
        last_seen_job_id=job_id,
        external_id="gid://shopify/Product/1",
        record_type="product",
        payload={
            "platform": "shopify",
            "shop_domain": "prospect.myshopify.com",
            "api_version": "2026-07",
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Same Shopify Product",
                "status": "ACTIVE",
                "variants": {"nodes": [], "pageInfo": {}},
                "media": {"nodes": [], "pageInfo": {}},
                "collections": {"nodes": [], "pageInfo": {}},
                "metafields": {"nodes": [], "pageInfo": {}},
            },
        },
        content_hash="a" * 64,
        source_updated_at=None,
    )


def test_identical_shopify_ids_remain_isolated_by_catalog_source() -> None:
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()
    source_a_id = uuid.uuid4()
    source_b_id = uuid.uuid4()
    source_a = _source(workspace_a, source_a_id)
    source_b = _source(workspace_b, source_b_id)

    batch_a = normalize_source_records(
        source_a,
        [_record(workspace_a, source_a_id, uuid.uuid4())],
    )
    batch_b = normalize_source_records(
        source_b,
        [_record(workspace_b, source_b_id, uuid.uuid4())],
    )

    assert len(batch_a.products) == 1
    assert len(batch_b.products) == 1
    assert batch_a.products[0].canonical_key != batch_b.products[0].canonical_key
    assert str(source_a_id) in batch_a.products[0].canonical_key
    assert str(source_b_id) in batch_b.products[0].canonical_key


# Branch-only CI maintenance verification marker; do not merge.
