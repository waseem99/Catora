from __future__ import annotations

import uuid

from catora_api.db.models.catalog import CatalogSource, SourceRecord
from catora_api.normalization.adapters import normalize_source_records, normalize_text


def source(source_type: str) -> CatalogSource:
    return CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name=source_type,
        source_type=source_type,
        status="active",
        config={},
    )


def record(
    catalog_source: CatalogSource,
    *,
    external_id: str,
    payload: dict[str, object],
) -> SourceRecord:
    return SourceRecord(
        id=uuid.uuid4(),
        workspace_id=catalog_source.workspace_id,
        catalog_source_id=catalog_source.id,
        ingestion_job_id=uuid.uuid4(),
        external_id=external_id,
        record_type="product",
        payload=payload,
        content_hash=uuid.uuid4().hex,
    )


def attribute_values(product: object) -> dict[str, object]:
    return {
        attribute.key: attribute.value
        for attribute in product.attributes  # type: ignore[attr-defined]
    }


def test_normalize_text_decodes_unicode_html_and_whitespace() -> None:
    assert normalize_text("  <p>Caf&eacute;\n Sofa</p>  ") == "Café Sofa"
    assert normalize_text("   ") is None


def test_csv_rows_group_into_product_and_variants() -> None:
    catalog_source = source("csv")
    first = record(
        catalog_source,
        external_id="p-1:v-1",
        payload={
            "product_id": "p-1",
            "title": " Cloud Sofa ",
            "variant_id": "v-1",
            "sku": "SOFA-BLUE",
            "description": "<p>Three-seat sofa</p>",
            "product_url": "https://example.com/cloud-sofa",
            "price": "1299.00",
            "currency": "USD",
            "availability": "in_stock",
            "category": "Sofas",
            "image_url": "https://example.com/blue.jpg",
        },
    )
    second = record(
        catalog_source,
        external_id="p-1:v-2",
        payload={
            "product_id": "p-1",
            "title": "Cloud Sofa",
            "variant_id": "v-2",
            "sku": "SOFA-GREY",
            "price": "1399.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "image_url": "https://example.com/grey.jpg",
        },
    )

    batch = normalize_source_records(catalog_source, [first, second])

    assert len(batch.products) == 1
    product = batch.products[0]
    assert product.title == "Cloud Sofa"
    assert product.canonical_key.endswith(":product:p-1")
    assert attribute_values(product)["description"] == "Three-seat sofa"
    assert len(product.variants) == 2
    assert product.variants[0].sku == "SOFA-BLUE"
    assert attribute_values(product.variants[0])["price"] == "1299.00"
    assert {image.variant_key for image in product.images} == {
        product.variants[0].canonical_key,
        product.variants[1].canonical_key,
    }


def test_shopify_snapshot_normalizes_nested_catalog_data() -> None:
    catalog_source = source("shopify")
    snapshot = record(
        catalog_source,
        external_id="gid://shopify/Product/1",
        payload={
            "platform": "shopify",
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Cloud Sofa",
                "descriptionHtml": "<p>Bouclé seating</p>",
                "vendor": "Demo Home",
                "productType": "Sofa",
                "status": "ACTIVE",
                "handle": "cloud-sofa",
                "onlineStoreUrl": "https://demo.myshopify.com/products/cloud-sofa",
                "tags": ["living-room", "three-seat"],
                "seo": {"title": "Cloud Sofa", "description": "Comfortable seating"},
                "collections": {
                    "nodes": [{"id": "c1", "title": "Sofas"}],
                },
                "metafields": {
                    "nodes": [
                        {
                            "namespace": "specs",
                            "key": "seating_capacity",
                            "type": "number_integer",
                            "value": "3",
                        }
                    ],
                },
                "variants": {
                    "nodes": [
                        {
                            "id": "gid://shopify/ProductVariant/1",
                            "title": "Blue",
                            "sku": "SOFA-BLUE",
                            "price": "1299.00",
                            "availableForSale": True,
                            "inventoryQuantity": 8,
                            "selectedOptions": [{"name": "Color", "value": "Blue"}],
                            "image": {
                                "url": "https://cdn.example.com/blue.jpg",
                                "altText": "Blue Cloud Sofa",
                            },
                        }
                    ]
                },
                "media": {"nodes": []},
            },
        },
    )

    batch = normalize_source_records(catalog_source, [snapshot])

    product = batch.products[0]
    values = attribute_values(product)
    assert values["description"] == "Bouclé seating"
    assert values["vendor"] == "Demo Home"
    assert values["metafield.specs.seating_capacity"] == 3
    assert values["collections"] == ["Sofas"]
    assert product.variants[0].option_values == {"Color": "Blue"}
    assert attribute_values(product.variants[0])["available_for_sale"] is True
    assert product.images[0].variant_key == product.variants[0].canonical_key


def test_public_snapshot_uses_json_ld_and_additional_properties() -> None:
    catalog_source = source("urls")
    snapshot = record(
        catalog_source,
        external_id="https://shop.example.com/products/cloud-sofa",
        payload={
            "platform": "public_web",
            "canonical_url": "https://shop.example.com/products/cloud-sofa",
            "products": [
                {
                    "@type": "Product",
                    "name": "Cloud Sofa",
                    "sku": "SOFA-1",
                    "description": "Three-seat sofa",
                    "brand": {"@type": "Brand", "name": "Demo Home"},
                    "image": ["https://shop.example.com/cloud.jpg"],
                    "offers": {
                        "@type": "Offer",
                        "price": "1299.00",
                        "priceCurrency": "USD",
                        "availability": "https://schema.org/InStock",
                    },
                    "additionalProperty": [
                        {"@type": "PropertyValue", "name": "Material", "value": "Bouclé"}
                    ],
                }
            ],
            "html_fallback": {},
        },
    )

    batch = normalize_source_records(catalog_source, [snapshot])

    product = batch.products[0]
    values = attribute_values(product)
    assert product.source_id == "SOFA-1"
    assert values["brand"] == "Demo Home"
    assert values["price"] == "1299.00"
    assert values["additional.material"] == "Bouclé"
    assert product.images[0].url.endswith("cloud.jpg")


def test_records_without_product_identity_are_rejected() -> None:
    catalog_source = source("csv")
    invalid = record(
        catalog_source,
        external_id="invalid",
        payload={"title": "No product ID"},
    )

    batch = normalize_source_records(catalog_source, [invalid])

    assert batch.products == ()
    assert batch.rejected_record_ids == (invalid.id,)
