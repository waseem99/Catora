from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorValidation,
)
from catora_api.secrets import SecretValue

SHOPIFY_API_VERSION = "2026-07"
_API_VERSION_PATTERN = re.compile(r"^\d{4}-(01|04|07|10)$")
SleepCallable = Callable[[float], Awaitable[None]]

VALIDATION_QUERY = """
query ValidateShop {
  shop {
    id
    name
    myshopifyDomain
  }
}
"""

PRODUCTS_QUERY = """
query CatoraProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {
    edges {
      cursor
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
        variants(first: 50) {
          nodes {
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
          pageInfo {
            hasNextPage
            endCursor
          }
        }
        media(first: 20) {
          nodes {
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
          pageInfo {
            hasNextPage
            endCursor
          }
        }
        collections(first: 20) {
          nodes {
            id
            title
            handle
            updatedAt
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
        metafields(first: 50) {
          nodes {
            id
            namespace
            key
            type
            value
            updatedAt
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


class ShopifyConnectorError(RuntimeError):
    pass


class ShopifyAuthorizationError(ShopifyConnectorError):
    pass


@dataclass(frozen=True, slots=True)
class ShopifyConnectorConfig:
    shop_domain: str
    access_token: SecretValue = field(repr=False)
    api_version: str = SHOPIFY_API_VERSION
    updated_after: datetime | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        domain = self.shop_domain.strip().lower()
        parsed = urlparse(domain if "://" in domain else f"https://{domain}")
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("Shopify shop domain must be an HTTPS hostname")
        if not parsed.hostname.endswith(".myshopify.com"):
            raise ValueError("Shopify shop domain must use the myshopify.com hostname")
        if parsed.port is not None or parsed.query or parsed.fragment:
            raise ValueError("Shopify shop domain must not include ports, query, or fragments")
        if not _API_VERSION_PATTERN.fullmatch(self.api_version):
            raise ValueError("Invalid Shopify API version")
        if self.updated_after is not None and self.updated_after.tzinfo is None:
            raise ValueError("updated_after must be timezone-aware")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "shop_domain", parsed.hostname)

    @property
    def endpoint(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"


class ShopifyCatalogConnector(CatalogConnector):
    source_type = "shopify"
    capabilities = ConnectorCapabilities(
        supports_incremental_sync=True,
        supports_resume=True,
        supports_schema_discovery=True,
        supports_remote_validation=True,
    )

    def __init__(
        self,
        config: ShopifyConnectorConfig,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: SleepCallable = asyncio.sleep,
        max_throttle_wait_seconds: float = 5.0,
    ) -> None:
        if max_throttle_wait_seconds < 0:
            raise ValueError("max_throttle_wait_seconds cannot be negative")
        self.config = config
        self._client = client
        self._sleep = sleep
        self._max_throttle_wait_seconds = max_throttle_wait_seconds
        self._last_cost: dict[str, float] = {}

    async def validate(self) -> ConnectorValidation:
        try:
            payload = await self._graphql(VALIDATION_QUERY, {})
            shop = self._mapping(self._mapping(payload.get("data")).get("shop"))
            if not shop.get("id") or not shop.get("myshopifyDomain"):
                return ConnectorValidation(
                    valid=False,
                    errors=("Shopify validation response was incomplete",),
                )
            return ConnectorValidation(
                valid=True,
                discovered_fields=("shop.id", "shop.name", "shop.myshopifyDomain"),
            )
        except ShopifyAuthorizationError:
            return ConnectorValidation(
                valid=False,
                errors=("Shopify authentication or product access failed",),
            )
        except (ShopifyConnectorError, httpx.HTTPError):
            return ConnectorValidation(
                valid=False,
                errors=("Shopify connection validation failed",),
            )

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        effective_page_size = min(page_size, 10)
        cursor_value = (checkpoint or {}).get("cursor")
        cursor = cursor_value if isinstance(cursor_value, str) and cursor_value else None
        search_query = self._incremental_query()

        while True:
            response = await self._graphql(
                PRODUCTS_QUERY,
                {
                    "first": effective_page_size,
                    "after": cursor,
                    "query": search_query,
                },
            )
            products = self._mapping(self._mapping(response.get("data")).get("products"))
            edges = products.get("edges")
            if not isinstance(edges, list):
                raise ShopifyConnectorError("Shopify products response was invalid")

            records: list[ConnectorRecord] = []
            end_cursor = cursor
            for edge_value in edges:
                edge = self._mapping(edge_value)
                node = self._mapping(edge.get("node"))
                product_id = node.get("id")
                if not isinstance(product_id, str) or not product_id:
                    raise ShopifyConnectorError("Shopify product response was invalid")
                edge_cursor = edge.get("cursor")
                if isinstance(edge_cursor, str) and edge_cursor:
                    end_cursor = edge_cursor
                warnings = self._nested_pagination_warnings(node)
                record_payload: dict[str, Any] = {
                    "platform": "shopify",
                    "shop_domain": self.config.shop_domain,
                    "api_version": self.config.api_version,
                    "product": node,
                }
                stable_payload = json.dumps(
                    record_payload,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                records.append(
                    ConnectorRecord(
                        external_id=product_id,
                        record_type="product",
                        payload=record_payload,
                        content_hash=hashlib.sha256(stable_payload.encode("utf-8")).hexdigest(),
                        source_updated_at=self._parse_datetime(node.get("updatedAt")),
                        warnings=warnings,
                    )
                )

            page_info = self._mapping(products.get("pageInfo"))
            has_next_page = page_info.get("hasNextPage") is True
            checkpoint_payload: dict[str, Any] = {
                "cursor": end_cursor,
                "updated_after": self._updated_after_text(),
                "cost": dict(self._last_cost),
            }
            if records:
                yield ConnectorPage(
                    records=tuple(records),
                    rejections=(),
                    next_checkpoint=checkpoint_payload,
                )
            if not has_next_page:
                break
            next_cursor = page_info.get("endCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ShopifyConnectorError("Shopify pagination cursor was missing")
            cursor = next_cursor

    async def _graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.config.access_token.get_secret_value(),
        }
        request_payload = {"query": query, "variables": dict(variables)}
        try:
            if self._client is not None:
                response = await self._client.post(
                    self.config.endpoint,
                    headers=headers,
                    json=request_payload,
                    timeout=self.config.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        self.config.endpoint,
                        headers=headers,
                        json=request_payload,
                    )
            if response.status_code in {401, 403}:
                raise ShopifyAuthorizationError("Shopify authorization failed")
            response.raise_for_status()
            body = response.json()
        except ShopifyAuthorizationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ShopifyConnectorError("Shopify request failed") from exc

        if not isinstance(body, dict):
            raise ShopifyConnectorError("Shopify response was invalid")
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            error_text = " ".join(
                str(self._mapping(item).get("message", "")) for item in errors
            ).lower()
            if "access denied" in error_text or "unauthorized" in error_text:
                raise ShopifyAuthorizationError("Shopify authorization failed")
            raise ShopifyConnectorError("Shopify GraphQL request failed")
        await self._apply_throttle(self._mapping(body.get("extensions")))
        return cast(dict[str, Any], body)

    async def _apply_throttle(self, extensions: Mapping[str, Any]) -> None:
        cost = self._mapping(extensions.get("cost"))
        throttle = self._mapping(cost.get("throttleStatus"))
        requested = self._number(cost.get("requestedQueryCost"))
        actual = self._number(cost.get("actualQueryCost"))
        available = self._number(throttle.get("currentlyAvailable"))
        restore_rate = self._number(throttle.get("restoreRate"))
        self._last_cost = {
            "requested": requested,
            "actual": actual,
            "currently_available": available,
            "restore_rate": restore_rate,
        }
        if restore_rate <= 0:
            return
        wait_seconds = max(0.0, (requested - available) / restore_rate)
        bounded_wait = min(wait_seconds, self._max_throttle_wait_seconds)
        if bounded_wait > 0:
            await self._sleep(bounded_wait)

    def _incremental_query(self) -> str | None:
        value = self._updated_after_text()
        return f"updated_at:>'{value}'" if value else None

    def _updated_after_text(self) -> str | None:
        if self.config.updated_after is None:
            return None
        return self.config.updated_after.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _nested_pagination_warnings(node: Mapping[str, Any]) -> tuple[str, ...]:
        warnings: list[str] = []
        for connection_name in ("variants", "media", "collections", "metafields"):
            connection = ShopifyCatalogConnector._mapping(node.get(connection_name))
            page_info = ShopifyCatalogConnector._mapping(connection.get("pageInfo"))
            if page_info.get("hasNextPage") is True:
                warnings.append(f"{connection_name}_truncated")
        return tuple(warnings)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ShopifyConnectorError("Shopify timestamp was invalid") from exc
        if parsed.tzinfo is None:
            raise ShopifyConnectorError("Shopify timestamp was invalid")
        return parsed

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}

    @staticmethod
    def _number(value: object) -> float:
        return float(value) if isinstance(value, int | float) else 0.0
