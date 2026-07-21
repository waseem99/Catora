from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from catora_api.connectors.base import CatalogConnector
from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping
from catora_api.connectors.shopify import ShopifyCatalogConnector, ShopifyConnectorConfig
from catora_api.db.models.catalog import CatalogSource
from catora_api.secrets import EnvironmentSecretResolver, SecretResolver
from catora_api.storage import ObjectStorage


async def connector_for_source(
    source: CatalogSource,
    storage: ObjectStorage,
    *,
    secret_resolver: SecretResolver | None = None,
) -> CatalogConnector:
    config: Mapping[str, Any] = source.config
    if source.source_type == "csv":
        return await _csv_connector(config, storage)
    if source.source_type == "shopify":
        return _shopify_connector(source, config, secret_resolver or EnvironmentSecretResolver())
    raise ValueError(f"Unsupported source type '{source.source_type}'")


async def _csv_connector(
    config: Mapping[str, Any], storage: ObjectStorage
) -> CsvCatalogConnector:
    object_key = config.get("object_key")
    mapping = config.get("mapping")
    if not isinstance(object_key, str) or not object_key:
        raise ValueError("CSV source object_key is missing")
    if not isinstance(mapping, dict):
        raise ValueError("CSV source mapping is missing")
    content = await storage.get_bytes(object_key)
    delimiter = config.get("delimiter")
    return CsvCatalogConnector(
        content=content,
        mapping=CsvMapping(**mapping),
        encoding=str(config.get("encoding") or "utf-8-sig"),
        delimiter=delimiter if isinstance(delimiter, str) else None,
    )


def _shopify_connector(
    source: CatalogSource,
    config: Mapping[str, Any],
    secret_resolver: SecretResolver,
) -> ShopifyCatalogConnector:
    shop_domain = config.get("shop_domain")
    if not isinstance(shop_domain, str) or not shop_domain:
        raise ValueError("Shopify shop domain is missing")
    if not source.credential_ref:
        raise ValueError("Shopify credential reference is missing")
    api_version = config.get("api_version")
    updated_after_value = config.get("updated_after")
    updated_after: datetime | None = None
    if isinstance(updated_after_value, str) and updated_after_value:
        try:
            updated_after = datetime.fromisoformat(updated_after_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Shopify incremental timestamp is invalid") from exc
    elif updated_after_value is not None:
        raise ValueError("Shopify incremental timestamp is invalid")

    return ShopifyCatalogConnector(
        ShopifyConnectorConfig(
            shop_domain=shop_domain,
            access_token=secret_resolver.resolve(source.credential_ref),
            api_version=str(api_version or "2026-07"),
            updated_after=updated_after,
        )
    )
