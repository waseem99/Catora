import uuid

import pytest
from pydantic import ValidationError

from catora_api.db.models.catalog import CatalogSource
from catora_api.ingestion.factory import connector_for_source
from catora_api.schemas.ingestion import CsvMappingRequest, CsvSourceCreateRequest


class FakeStorage:
    async def get_bytes(self, key: str) -> bytes:
        assert key == "workspaces/w/catalog.csv"
        return b"id,title\np1,Sofa\n"


def test_csv_source_contract_strips_mapping_columns() -> None:
    request = CsvSourceCreateRequest(
        name="Primary catalog",
        object_key="workspaces/w/catalog.csv",
        mapping=CsvMappingRequest(product_id=" id ", title=" title "),
    )

    assert request.mapping.product_id == "id"
    assert request.mapping.title == "title"


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
