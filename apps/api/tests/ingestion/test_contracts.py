import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from catora_api.connectors.public_catalog import PublicCatalogConnector
from catora_api.connectors.shopify import ShopifyCatalogConnector
from catora_api.connectors.shopify_bulk import ShopifyBulkCatalogConnector
from catora_api.db.models.catalog import CatalogSource
from catora_api.ingestion.factory import connector_for_source
from catora_api.schemas.ingestion import (
    CsvMappingRequest,
    CsvSourceCreateRequest,
    PublicCatalogSourceCreateRequest,
    ShopifySourceCreateRequest,
)
from catora_api.secrets import SecretValue


class FakeStorage:
    async def get_bytes(self, key: str) -> bytes:
        assert key == "workspaces/w/catalog.csv"
        return b"id,title\np1,Sofa\n"


class FakeSecretResolver:
    def __init__(self) -> None:
        self.references: list[str] = []

    def resolve(self, reference: str) -> SecretValue:
        self.references.append(reference)
        return SecretValue("resolved-token")


def test_csv_source_contract_strips_mapping_columns() -> None:
    request = CsvSourceCreateRequest(
        name="Primary catalog",
        object_key="workspaces/w/catalog.csv",
        mapping=CsvMappingRequest(product_id=" id ", title=" title "),
    )

    assert request.mapping.product_id == "id"
    assert request.mapping.title == "title"


def test_csv_source_contract_rejects_blank_required_column() -> None:
    with pytest.raises(ValidationError):
        CsvMappingRequest(product_id="   ", title="title")


def test_csv_source_contract_rejects_multi_character_delimiter() -> None:
    with pytest.raises(ValidationError):
        CsvSourceCreateRequest(
            name="Primary catalog",
            object_key="workspaces/w/catalog.csv",
            delimiter=",,",
            mapping=CsvMappingRequest(product_id="id", title="title"),
        )


def test_shopify_source_contract_normalizes_domain_without_raw_token() -> None:
    request = ShopifySourceCreateRequest(
        name="Primary Shopify store",
        shop_domain="https://Demo-Store.myshopify.com/",
        credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
        updated_after="2026-07-01T00:00:00Z",
    )

    assert request.shop_domain == "demo-store.myshopify.com"
    assert request.updated_after is not None

    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest.model_validate(
            {
                "name": "Unsafe source",
                "shop_domain": "demo-store.myshopify.com",
                "credential_ref": "env:CATORA_CONNECTOR_SECRET_DEMO",
                "access_token": "raw-token-must-not-be-accepted",
            }
        )


def test_shopify_source_contract_rejects_unsafe_values() -> None:
    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest(
            name="Unsafe source",
            shop_domain="https://example.com",
            credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
        )
    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest(
            name="Unsafe source",
            shop_domain="demo-store.myshopify.com",
            credential_ref="env:SHOPIFY_TOKEN",
        )
    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest(
            name="Unsafe source",
            shop_domain="demo-store.myshopify.com",
            credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
            updated_after=datetime(2026, 7, 1),
        )


def test_public_source_contract_requires_same_host_and_authorization() -> None:
    request = PublicCatalogSourceCreateRequest(
        name="Public catalog",
        source_type="urls",
        product_urls=[
            "https://SHOP.example.com/products/one",
            "https://shop.example.com/products/two",
        ],
        authorized_domain_confirmed=True,
    )

    assert request.product_urls == [
        "https://shop.example.com/products/one",
        "https://shop.example.com/products/two",
    ]

    with pytest.raises(ValidationError):
        PublicCatalogSourceCreateRequest(
            name="Unauthorized",
            source_type="urls",
            product_urls=["https://shop.example.com/products/one"],
            authorized_domain_confirmed=False,
        )
    with pytest.raises(ValidationError):
        PublicCatalogSourceCreateRequest(
            name="Cross host",
            source_type="urls",
            product_urls=[
                "https://shop.example.com/products/one",
                "https://other.example.com/products/two",
            ],
            authorized_domain_confirmed=True,
        )


def test_public_source_contract_requires_correct_shape() -> None:
    with pytest.raises(ValidationError):
        PublicCatalogSourceCreateRequest(
            name="Invalid sitemap",
            source_type="sitemap",
            product_urls=["https://shop.example.com/products/one"],
            authorized_domain_confirmed=True,
        )
    with pytest.raises(ValidationError):
        PublicCatalogSourceCreateRequest(
            name="Invalid URLs",
            source_type="urls",
            start_url="https://shop.example.com/sitemap.xml",
            authorized_domain_confirmed=True,
        )


@pytest.mark.asyncio
async def test_factory_builds_csv_connector_from_source_config() -> None:
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="CSV",
        source_type="csv",
        status="draft",
        config={
            "object_key": "workspaces/w/catalog.csv",
            "mapping": {"product_id": "id", "title": "title"},
            "encoding": "utf-8",
        },
    )

    connector = await connector_for_source(
        source,
        FakeStorage(),  # type: ignore[arg-type]
    )

    assert connector.source_type == "csv"
    assert connector.mapping.product_id == "id"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_factory_builds_shopify_connector_from_secret_reference() -> None:
    resolver = FakeSecretResolver()
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Shopify",
        source_type="shopify",
        status="draft",
        credential_ref="env:CATORA_CONNECTOR_SECRET_SHOPIFY_DEMO",
        config={
            "shop_domain": "demo-store.myshopify.com",
            "api_version": "2026-07",
            "updated_after": "2026-07-01T00:00:00Z",
        },
    )

    connector = await connector_for_source(
        source,
        FakeStorage(),  # type: ignore[arg-type]
        secret_resolver=resolver,
    )

    assert isinstance(connector, ShopifyCatalogConnector)
    assert not isinstance(connector, ShopifyBulkCatalogConnector)
    assert connector.config.updated_after is not None
    assert resolver.references == [
        "env:CATORA_CONNECTOR_SECRET_SHOPIFY_DEMO"
    ]
    assert "resolved-token" not in repr(connector.config)
    assert "access_token" not in source.config


@pytest.mark.asyncio
async def test_factory_uses_bulk_only_for_public_initial_sync() -> None:
    resolver = FakeSecretResolver()
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Public Shopify",
        source_type="shopify",
        status="ready",
        credential_ref="env:CATORA_CONNECTOR_SECRET_SHOPIFY_PUBLIC",
        config={
            "shop_domain": "prospect-store.myshopify.com",
            "api_version": "2026-07",
            "updated_after": None,
            "distribution": "public",
        },
    )

    connector = await connector_for_source(
        source,
        FakeStorage(),  # type: ignore[arg-type]
        secret_resolver=resolver,
    )

    assert isinstance(connector, ShopifyBulkCatalogConnector)
    assert connector.config.updated_after is None
    assert resolver.references == [
        "env:CATORA_CONNECTOR_SECRET_SHOPIFY_PUBLIC"
    ]


@pytest.mark.asyncio
async def test_factory_builds_bounded_public_catalog_connector() -> None:
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Public catalog",
        source_type="urls",
        status="draft",
        config={
            "start_url": None,
            "product_urls": [
                "https://shop.example.com/products/one"
            ],
            "authorized_domain_confirmed": True,
            "max_products": 25,
            "max_sitemaps": 5,
            "crawl_delay_seconds": 1.0,
        },
    )

    connector = await connector_for_source(
        source,
        FakeStorage(),  # type: ignore[arg-type]
    )

    assert isinstance(connector, PublicCatalogConnector)
    assert connector.source_type == "urls"
    assert connector.config.max_products == 25
    assert connector.config.authorized_domain_confirmed is True
