import uuid

import pytest
from pydantic import ValidationError

from catora_api.connectors.shopify import ShopifyCatalogConnector
from catora_api.db.models.catalog import CatalogSource
from catora_api.ingestion.factory import connector_for_source
from catora_api.schemas.ingestion import CsvMappingRequest, CsvSourceCreateRequest
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

    connector = await connector_for_source(source, FakeStorage())  # type: ignore[arg-type]

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
    assert connector.config.updated_after is not None
    assert resolver.references == ["env:CATORA_CONNECTOR_SECRET_SHOPIFY_DEMO"]
    assert "resolved-token" not in repr(connector.config)
    assert "access_token" not in source.config
