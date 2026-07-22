import pytest

from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping
from catora_api.connectors.registry import ConnectorRegistry


def test_registry_registers_and_creates_connector() -> None:
    registry = ConnectorRegistry()
    registry.register("csv", CsvCatalogConnector)

    connector = registry.create(
        "CSV",
        content="id,title\np-1,Sofa\n",
        mapping=CsvMapping(product_id="id", title="title"),
    )
    assert isinstance(connector, CsvCatalogConnector)
    assert registry.source_types == ("csv",)


def test_registry_rejects_duplicate_registration() -> None:
    registry = ConnectorRegistry()
    registry.register("csv", CsvCatalogConnector)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("CSV", CsvCatalogConnector)
