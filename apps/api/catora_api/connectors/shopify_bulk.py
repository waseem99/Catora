from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from catora_api.connectors.base import ConnectorPage, ConnectorRecord
from catora_api.connectors.shopify import (
    ShopifyCatalogConnector,
    ShopifyConnectorConfig,
    ShopifyConnectorError,
)

BULK_PRODUCTS_QUERY = """
{
  products {
    edges {
      node {
        id
        legacyResourceId
        title
        handle
        descriptionHtml
        vendor
        productType
        status
        tags
        createdAt
        updatedAt
        publishedAt
        onlineStoreUrl
        seo {
          title
          description
        }
        options {
          id
          name
          optionValues {
            id
            name
          }
        }
        variants {
          edges {
            node {
              id
              legacyResourceId
              title
              displayName
              sku
              barcode
              price
              compareAtPrice
              availableForSale
              inventoryQuantity
              createdAt
              updatedAt
              selectedOptions {
                name
                value
              }
              image {
                id
                url
                altText
                width
                height
              }
            }
          }
        }
        media {
          edges {
            node {
              __typename
              id
              alt
              ... on MediaImage {
                image {
                  id
                  url
                  width
                  height
                }
              }
            }
          }
        }
        collections {
          edges {
            node {
              id
              title
              handle
              updatedAt
            }
          }
        }
        metafields {
          edges {
            node {
              id
              namespace
              key
              type
              value
              updatedAt
            }
          }
        }
      }
    }
  }
}
"""

BULK_RUN_MUTATION = """
mutation CatoraBulkProducts($query: String!, $groupObjects: Boolean!) {
  bulkOperationRunQuery(query: $query, groupObjects: $groupObjects) {
    bulkOperation {
      id
      status
    }
    userErrors {
      field
      message
    }
  }
}
"""

BULK_STATUS_QUERY = """
query CatoraBulkOperation($id: ID!) {
  node(id: $id) {
    ... on BulkOperation {
      id
      status
      errorCode
      createdAt
      completedAt
      objectCount
      rootObjectCount
      fileSize
      url
      partialDataUrl
    }
  }
}
"""

_TERMINAL_FAILURE_STATUSES = {"CANCELED", "CANCELING", "EXPIRED", "FAILED"}
_MEDIA_GID_PREFIXES = (
    "gid://shopify/MediaImage/",
    "gid://shopify/Video/",
    "gid://shopify/ExternalVideo/",
    "gid://shopify/Model3d/",
)


@dataclass(frozen=True, slots=True)
class ShopifyBulkOperationSnapshot:
    operation_id: str
    status: str
    object_count: int
    root_object_count: int
    file_size: int
    created_at: datetime | None
    completed_at: datetime | None
    result_url: str | None
    partial_data_url: str | None
    error_code: str | None

    def checkpoint(self, *, products_emitted: int) -> dict[str, object]:
        expires_at = (
            self.completed_at + timedelta(days=7)
            if self.completed_at is not None
            else None
        )
        return {
            "strategy": "bulk_initial",
            "operation_id": self.operation_id,
            "operation_status": self.status,
            "products_emitted": products_emitted,
            "object_count": self.object_count,
            "root_object_count": self.root_object_count,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "result_url_expires_at": expires_at.isoformat() if expires_at else None,
        }


class ShopifyBulkCatalogConnector(ShopifyCatalogConnector):
    """Initial Shopify extraction through one bounded, resumable bulk query."""

    def __init__(
        self,
        config: ShopifyConnectorConfig,
        *,
        client: httpx.AsyncClient | None = None,
        poll_interval_seconds: float = 1.0,
        max_wait_seconds: float = 900.0,
    ) -> None:
        super().__init__(config, client=client)
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be positive")
        self._poll_interval_seconds = poll_interval_seconds
        self._max_wait_seconds = max_wait_seconds

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        effective_page_size = min(page_size, 1000)
        operation_id = self._checkpoint_text(checkpoint, "operation_id")
        products_to_skip = self._checkpoint_int(checkpoint, "products_emitted")
        if operation_id is None:
            operation_id = await self._submit_bulk_operation()

        operation = await self._wait_for_operation(operation_id)
        if operation.result_url is None:
            raise ShopifyConnectorError(
                "Shopify bulk operation completed without a result"
            )

        records: list[ConnectorRecord] = []
        products_seen = 0
        products_emitted = products_to_skip
        current_product: dict[str, Any] | None = None

        async for line_number, payload in self._result_objects(operation.result_url):
            parent_id = payload.pop("__parentId", None)
            if parent_id is None:
                if current_product is not None:
                    products_seen += 1
                    if products_seen > products_to_skip:
                        records.append(self._product_record(current_product))
                        products_emitted += 1
                        if len(records) >= effective_page_size:
                            yield ConnectorPage(
                                records=tuple(records),
                                rejections=(),
                                next_checkpoint=operation.checkpoint(
                                    products_emitted=products_emitted
                                ),
                            )
                            records = []
                current_product = self._start_product(payload, line_number=line_number)
                continue

            if current_product is None:
                raise ShopifyConnectorError(
                    "Shopify bulk result contained a child before its product"
                )
            product_id = current_product.get("id")
            if parent_id != product_id:
                raise ShopifyConnectorError(
                    "Shopify bulk result was not grouped by product"
                )
            self._append_child(
                current_product,
                payload,
                line_number=line_number,
            )

        if current_product is not None:
            products_seen += 1
            if products_seen > products_to_skip:
                records.append(self._product_record(current_product))
                products_emitted += 1

        if products_seen != operation.root_object_count:
            raise ShopifyConnectorError(
                "Shopify bulk product count did not reconcile"
            )
        if products_emitted != operation.root_object_count:
            raise ShopifyConnectorError(
                "Shopify bulk resume count did not reconcile"
            )
        if records:
            yield ConnectorPage(
                records=tuple(records),
                rejections=(),
                next_checkpoint=operation.checkpoint(
                    products_emitted=products_emitted
                ),
            )

    async def _submit_bulk_operation(self) -> str:
        response = await self._graphql(
            BULK_RUN_MUTATION,
            {
                "query": BULK_PRODUCTS_QUERY,
                "groupObjects": True,
            },
        )
        data = self._mapping(response.get("data"))
        result = self._mapping(data.get("bulkOperationRunQuery"))
        user_errors = result.get("userErrors")
        if isinstance(user_errors, list) and user_errors:
            raise ShopifyConnectorError("Shopify bulk query was rejected")
        operation = self._mapping(result.get("bulkOperation"))
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            raise ShopifyConnectorError(
                "Shopify bulk operation response was incomplete"
            )
        return operation_id

    async def _wait_for_operation(
        self,
        operation_id: str,
    ) -> ShopifyBulkOperationSnapshot:
        elapsed = 0.0
        while True:
            operation = await self._operation(operation_id)
            if operation.status == "COMPLETED":
                return operation
            if operation.status in _TERMINAL_FAILURE_STATUSES:
                raise ShopifyConnectorError(
                    "Shopify bulk operation did not complete"
                )
            if elapsed >= self._max_wait_seconds:
                raise ShopifyConnectorError("Shopify bulk operation timed out")
            await self._sleep(self._poll_interval_seconds)
            elapsed += self._poll_interval_seconds

    async def _operation(self, operation_id: str) -> ShopifyBulkOperationSnapshot:
        response = await self._graphql(BULK_STATUS_QUERY, {"id": operation_id})
        data = self._mapping(response.get("data"))
        node = self._mapping(data.get("node"))
        returned_id = node.get("id")
        status = node.get("status")
        if returned_id != operation_id or not isinstance(status, str):
            raise ShopifyConnectorError(
                "Shopify bulk operation status was unavailable"
            )
        return ShopifyBulkOperationSnapshot(
            operation_id=operation_id,
            status=status.upper(),
            object_count=self._nonnegative_int(node.get("objectCount")),
            root_object_count=self._nonnegative_int(node.get("rootObjectCount")),
            file_size=self._nonnegative_int(node.get("fileSize")),
            created_at=self._optional_datetime(node.get("createdAt")),
            completed_at=self._optional_datetime(node.get("completedAt")),
            result_url=self._optional_url(node.get("url")),
            partial_data_url=self._optional_url(node.get("partialDataUrl")),
            error_code=self._optional_text(node.get("errorCode")),
        )

    async def _result_objects(
        self,
        result_url: str,
    ) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        if not result_url.startswith("https://"):
            raise ShopifyConnectorError("Shopify bulk result URL was invalid")

        async def iterate(client: httpx.AsyncClient) -> AsyncIterator[tuple[int, dict[str, Any]]]:
            try:
                async with client.stream(
                    "GET",
                    result_url,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    response.raise_for_status()
                    line_number = 0
                    async for raw_line in response.aiter_lines():
                        line_number += 1
                        if not raw_line.strip():
                            continue
                        try:
                            value = json.loads(raw_line)
                        except json.JSONDecodeError as exc:
                            raise ShopifyConnectorError(
                                "Shopify bulk result contained invalid JSONL"
                            ) from exc
                        if not isinstance(value, dict):
                            raise ShopifyConnectorError(
                                "Shopify bulk result line was invalid"
                            )
                        yield line_number, value
            except ShopifyConnectorError:
                raise
            except httpx.HTTPError as exc:
                raise ShopifyConnectorError(
                    "Shopify bulk result download failed"
                ) from exc

        if self._client is not None:
            async for item in iterate(self._client):
                yield item
            return
        async with httpx.AsyncClient() as client:
            async for item in iterate(client):
                yield item

    def _start_product(
        self,
        payload: dict[str, Any],
        *,
        line_number: int,
    ) -> dict[str, Any]:
        product_id = payload.get("id")
        if not isinstance(product_id, str) or not product_id.startswith(
            "gid://shopify/Product/"
        ):
            raise ShopifyConnectorError(
                f"Shopify bulk result line {line_number} was not a product"
            )
        product = dict(payload)
        for name in ("variants", "media", "collections", "metafields"):
            product[name] = {
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        return product

    def _append_child(
        self,
        product: dict[str, Any],
        child: dict[str, Any],
        *,
        line_number: int,
    ) -> None:
        child_id = child.get("id")
        if not isinstance(child_id, str) or not child_id:
            raise ShopifyConnectorError(
                f"Shopify bulk child line {line_number} had no ID"
            )
        if child_id.startswith("gid://shopify/ProductVariant/"):
            connection_name = "variants"
        elif child_id.startswith(_MEDIA_GID_PREFIXES):
            connection_name = "media"
        elif child_id.startswith("gid://shopify/Collection/"):
            connection_name = "collections"
        elif child_id.startswith("gid://shopify/Metafield/"):
            connection_name = "metafields"
        else:
            raise ShopifyConnectorError(
                f"Shopify bulk child line {line_number} had an unsupported type"
            )
        connection = self._mapping(product.get(connection_name))
        nodes = connection.get("nodes")
        if not isinstance(nodes, list):
            raise ShopifyConnectorError(
                "Shopify bulk product assembly failed"
            )
        nodes.append(child)

    def _product_record(self, product: Mapping[str, Any]) -> ConnectorRecord:
        product_id = product.get("id")
        if not isinstance(product_id, str) or not product_id:
            raise ShopifyConnectorError("Shopify bulk product ID was missing")
        record_payload: dict[str, Any] = {
            "platform": "shopify",
            "shop_domain": self.config.shop_domain,
            "api_version": self.config.api_version,
            "product": dict(product),
        }
        stable_payload = json.dumps(
            record_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ConnectorRecord(
            external_id=product_id,
            record_type="product",
            payload=record_payload,
            content_hash=hashlib.sha256(stable_payload.encode("utf-8")).hexdigest(),
            source_updated_at=self._parse_datetime(product.get("updatedAt")),
            warnings=(),
        )

    @staticmethod
    def _checkpoint_text(
        checkpoint: Mapping[str, Any] | None,
        key: str,
    ) -> str | None:
        value = (checkpoint or {}).get(key)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _checkpoint_int(
        checkpoint: Mapping[str, Any] | None,
        key: str,
    ) -> int:
        value = (checkpoint or {}).get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    @staticmethod
    def _nonnegative_int(value: object) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return 0

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @classmethod
    def _optional_url(cls, value: object) -> str | None:
        text = cls._optional_text(value)
        return text if text is not None and text.startswith("https://") else None

    @classmethod
    def _optional_datetime(cls, value: object) -> datetime | None:
        text = cls._optional_text(value)
        if text is None:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ShopifyConnectorError(
                "Shopify bulk operation timestamp was invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise ShopifyConnectorError(
                "Shopify bulk operation timestamp was invalid"
            )
        return parsed.astimezone(UTC)
