from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from catora_api.connectors.base import CatalogConnector
from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping
from catora_api.connectors.public_catalog import (
    PublicCatalogConnector,
    PublicCatalogConnectorConfig,
)
from catora_api.connectors.shopify import (
    ShopifyCatalogConnector,
    ShopifyConnectorConfig,
)
from catora_api.db.models.catalog import CatalogSource
from catora_api.secrets import EnvironmentSecretResolver, SecretResolver, SecretValue
from catora_api.shopify.installations import (
    SHOPIFY_CREDENTIAL_SCHEME,
    ShopifyInstallationService,
    parse_credential_reference,
)
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
        return await _shopify_connector(
            source,
            config,
            secret_resolver=secret_resolver,
        )
    if source.source_type in {"sitemap", "urls"}:
        return _public_catalog_connector(source.source_type, config)
    raise ValueError(f"Unsupported source type '{source.source_type}'")


async def _csv_connector(
    config: Mapping[str, Any],
    storage: ObjectStorage,
) -> CsvCatalogConnector:
    object_key = config.get("object_key")
    mapping = config.get("mapping")
    if not isinstance(object_key, str) or not object_key:
        raise ValueError("CSV source object_key is missing")
    if not isinstance(mapping, dict):
        raise ValueError("CSV source mapping is missing")
    content = await storage.get_bytes(object_key)
    delimiter = config.get("delimiter")
    profile = config.get("profile", "generic")
    if profile not in {"generic", "shopify"}:
        raise ValueError("CSV source profile is invalid")
    standard_shopify_mapping = (
        mapping.get("product_id") == "Handle" and mapping.get("title") == "Title"
    )
    return CsvCatalogConnector(
        content=content,
        mapping=CsvMapping(**mapping),
        encoding=str(config.get("encoding") or "utf-8-sig"),
        delimiter=delimiter if isinstance(delimiter, str) else None,
        shopify_profile=profile == "shopify" or standard_shopify_mapping,
    )


async def _resolve_shopify_credential(
    reference: str,
    *,
    secret_resolver: SecretResolver | None,
) -> SecretValue:
    if reference.startswith(f"{SHOPIFY_CREDENTIAL_SCHEME}:"):
        installation_id = parse_credential_reference(reference)
        return await ShopifyInstallationService().resolve_access_token(installation_id)
    resolver = secret_resolver or EnvironmentSecretResolver()
    return resolver.resolve(reference)


async def _shopify_connector(
    source: CatalogSource,
    config: Mapping[str, Any],
    *,
    secret_resolver: SecretResolver | None,
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
            updated_after = datetime.fromisoformat(
                updated_after_value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("Shopify incremental timestamp is invalid") from exc
    elif updated_after_value is not None:
        raise ValueError("Shopify incremental timestamp is invalid")

    return ShopifyCatalogConnector(
        ShopifyConnectorConfig(
            shop_domain=shop_domain,
            access_token=await _resolve_shopify_credential(
                source.credential_ref,
                secret_resolver=secret_resolver,
            ),
            api_version=str(api_version or "2026-07"),
            updated_after=updated_after,
        )
    )


def _public_catalog_connector(
    source_type: str,
    config: Mapping[str, Any],
) -> PublicCatalogConnector:
    start_url = config.get("start_url")
    product_urls_value = config.get("product_urls", [])
    if not isinstance(product_urls_value, list):
        raise ValueError("Public catalog product URLs are invalid")
    product_urls = tuple(
        value for value in product_urls_value if isinstance(value, str)
    )
    if len(product_urls) != len(product_urls_value):
        raise ValueError("Public catalog product URLs are invalid")
    authorized = config.get("authorized_domain_confirmed") is True
    max_products = config.get("max_products", 100)
    max_sitemaps = config.get("max_sitemaps", 10)
    crawl_delay = config.get("crawl_delay_seconds", 0.5)
    if start_url is not None and not isinstance(start_url, str):
        raise ValueError("Public catalog start URL is invalid")
    if not isinstance(max_products, int):
        raise ValueError("Public catalog max_products is invalid")
    if not isinstance(max_sitemaps, int):
        raise ValueError("Public catalog max_sitemaps is invalid")
    if not isinstance(crawl_delay, int | float):
        raise ValueError("Public catalog crawl delay is invalid")
    return PublicCatalogConnector(
        PublicCatalogConnectorConfig(
            source_type=source_type,
            start_url=start_url,
            product_urls=product_urls,
            authorized_domain_confirmed=authorized,
            max_products=max_products,
            max_sitemaps=max_sitemaps,
            crawl_delay_seconds=float(crawl_delay),
        )
    )
