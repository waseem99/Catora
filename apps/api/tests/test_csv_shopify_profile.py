from __future__ import annotations

import asyncio

from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping


async def _records(
    connector: CsvCatalogConnector,
    *,
    checkpoint: dict[str, int] | None = None,
) -> tuple[list[object], list[object]]:
    records: list[object] = []
    rejections: list[object] = []
    async for page in connector.pages(checkpoint=checkpoint, page_size=100):
        records.extend(page.records)
        rejections.extend(page.rejections)
    return records, rejections


def _connector(*, shopify_profile: bool) -> CsvCatalogConnector:
    content = (
        "Handle,Title,Variant SKU,Body (HTML),Type,Image Src\n"
        "cloudline-sofa,Cloudline Sofa,CLOUD-1,<p>Compact sofa</p>,Sofas,https://example.test/1.jpg\n"
        "cloudline-sofa,,CLOUD-2,,,\n"
    )
    return CsvCatalogConnector(
        content=content,
        mapping=CsvMapping(
            product_id="Handle",
            title="Title",
            variant_id="Variant SKU",
            sku="Variant SKU",
            description="Body (HTML)",
            category="Type",
            image_url="Image Src",
        ),
        shopify_profile=shopify_profile,
    )


def test_shopify_profile_inherits_title_for_variant_rows() -> None:
    records, rejections = asyncio.run(_records(_connector(shopify_profile=True)))

    assert len(records) == 2
    assert not rejections
    second = records[1]
    assert second.external_id == "cloudline-sofa:CLOUD-2"
    assert second.payload["title"] == "Cloudline Sofa"


def test_generic_profile_rejects_blank_variant_title() -> None:
    records, rejections = asyncio.run(_records(_connector(shopify_profile=False)))

    assert len(records) == 1
    assert len(rejections) == 1
    assert rejections[0].reason == "Missing product title"


def test_shopify_profile_preserves_inheritance_when_resuming() -> None:
    records, rejections = asyncio.run(
        _records(_connector(shopify_profile=True), checkpoint={"row": 1})
    )

    assert len(records) == 1
    assert not rejections
    assert records[0].external_id == "cloudline-sofa:CLOUD-2"
    assert records[0].payload["title"] == "Cloudline Sofa"
