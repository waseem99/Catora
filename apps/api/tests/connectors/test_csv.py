import pytest

from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping


@pytest.mark.asyncio
async def test_csv_connector_validates_and_pages_with_rejections() -> None:
    connector = CsvCatalogConnector(
        content=(
            "product_id,title,variant_id,sku,price\n"
            "p-1,Cloud Sofa,v-1,SOFA-1,1299\n"
            ",Missing identifier,v-2,SOFA-2,999\n"
            "p-2,,v-3,SOFA-3,799\n"
            "p-3,Lounge Chair,,,499\n"
        ),
        mapping=CsvMapping(
            product_id="product_id",
            title="title",
            variant_id="variant_id",
            sku="sku",
            price="price",
        ),
    )

    validation = await connector.validate()
    assert validation.valid
    assert validation.discovered_fields == (
        "product_id",
        "title",
        "variant_id",
        "sku",
        "price",
    )

    pages = [page async for page in connector.pages(page_size=2)]
    assert len(pages) == 2
    assert pages[0].next_checkpoint == {"row": 2}
    assert pages[1].next_checkpoint == {"row": 4}
    assert [record.external_id for page in pages for record in page.records] == [
        "p-1:v-1",
        "p-3",
    ]
    assert [rejection.reason for page in pages for rejection in page.rejections] == [
        "Missing product identifier",
        "Missing product title",
    ]


@pytest.mark.asyncio
async def test_csv_connector_resumes_after_checkpoint() -> None:
    connector = CsvCatalogConnector(
        content="id,title\np-1,Sofa\np-2,Chair\np-3,Desk\n",
        mapping=CsvMapping(product_id="id", title="title"),
    )

    pages = [page async for page in connector.pages(checkpoint={"row": 2}, page_size=10)]
    assert len(pages) == 1
    assert [record.external_id for record in pages[0].records] == ["p-3"]
    assert pages[0].next_checkpoint == {"row": 3}


@pytest.mark.asyncio
async def test_csv_connector_hash_is_deterministic() -> None:
    connector = CsvCatalogConnector(
        content="id,title,sku\np-1,Sofa,S-1\n",
        mapping=CsvMapping(product_id="id", title="title", sku="sku"),
    )
    first = [page async for page in connector.pages()]
    second = [page async for page in connector.pages()]
    assert first[0].records[0].content_hash == second[0].records[0].content_hash


@pytest.mark.asyncio
async def test_csv_connector_rejects_missing_required_mapping_column() -> None:
    connector = CsvCatalogConnector(
        content="id,name\np-1,Sofa\n",
        mapping=CsvMapping(product_id="id", title="title"),
    )
    validation = await connector.validate()
    assert not validation.valid
    assert "Mapped column 'title' is missing" in validation.errors


@pytest.mark.asyncio
async def test_csv_connector_enforces_page_size_bounds() -> None:
    connector = CsvCatalogConnector(
        content="id,title\np-1,Sofa\n",
        mapping=CsvMapping(product_id="id", title="title"),
    )
    with pytest.raises(ValueError, match="page_size"):
        _ = [page async for page in connector.pages(page_size=0)]
