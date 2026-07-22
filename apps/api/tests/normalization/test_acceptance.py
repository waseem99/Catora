from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catora_api.db.models.catalog import CatalogSource, Product, SourceRecord
from catora_api.identity_resolution.service import (
    CatalogIdentityService,
    _pair,
    _ProductProfile,
)
from catora_api.normalization.adapters import normalize_source_records
from catora_api.normalization.pipeline import normalize_batch_urls, normalize_url


def _source(source_type: str) -> CatalogSource:
    return CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name=source_type,
        source_type=source_type,
        status="active",
        config={},
    )


def _record(
    source: CatalogSource,
    *,
    external_id: str,
    payload: dict[str, object],
) -> SourceRecord:
    return SourceRecord(
        id=uuid.uuid4(),
        workspace_id=source.workspace_id,
        catalog_source_id=source.id,
        ingestion_job_id=uuid.uuid4(),
        external_id=external_id,
        record_type="product",
        payload=payload,
        content_hash=uuid.uuid4().hex,
    )


def _attributes(product: object) -> dict[str, object]:
    return {
        attribute.key: attribute
        for attribute in product.attributes  # type: ignore[attr-defined]
    }


def _shopify_payload(selected_options: list[dict[str, str]]) -> dict[str, object]:
    return {
        "platform": "shopify",
        "product": {
            "id": "gid://shopify/Product/1",
            "title": "Cloud Sofa",
            "variants": {
                "nodes": [
                    {
                        "id": "gid://shopify/ProductVariant/1",
                        "title": "Blue / Large",
                        "sku": "SOFA-BLUE-L",
                        "selectedOptions": selected_options,
                    }
                ]
            },
            "media": {"nodes": []},
        },
    }


def _profile(
    *,
    canonical_key: str,
    gtin: str,
) -> _ProductProfile:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    product = Product(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        canonical_key=canonical_key,
        title="Cloud Sofa",
        status="active",
        created_at=now,
        updated_at=now,
    )
    return _ProductProfile(
        product=product,
        title_key="cloud sofa",
        title_tokens=("cloud", "sofa"),
        brands=frozenset({"demo-home"}),
        gtins=frozenset({gtin}),
        mpns=frozenset(),
        skus=frozenset(),
    )


def test_normalize_url_is_conservative_and_stable() -> None:
    assert normalize_url(" HTTPS://BÜCHER.example:443/catalog#section ") == (
        "https://xn--bcher-kva.example/catalog"
    )
    assert normalize_url("http://Example.com:80") == "http://example.com/"
    assert normalize_url("ftp://example.com/catalog") is None
    assert normalize_url("https://user:secret@example.com/catalog") is None
    assert normalize_url("https://example.com/bad path") is None


def test_public_product_and_canonical_urls_remain_separate_with_provenance() -> None:
    source = _source("urls")
    raw_product_url = (
        "https://SHOP.example.com:443/products/cloud-sofa?variant=blue#details"
    )
    raw_canonical_url = "https://shop.example.com:443/products/cloud-sofa#canonical"
    record = _record(
        source,
        external_id="https://shop.example.com/discovery/cloud-sofa#source",
        payload={
            "platform": "public_web",
            "canonical_url": raw_canonical_url,
            "products": [
                {
                    "@type": "Product",
                    "name": "Cloud Sofa",
                    "sku": "SOFA-1",
                    "url": raw_product_url,
                }
            ],
            "html_fallback": {},
        },
    )

    adapted = normalize_source_records(source, [record])
    normalized = normalize_batch_urls(adapted, source=source, records=[record])
    product = normalized.products[0]
    attributes = _attributes(product)
    product_url = attributes["product_url"]
    canonical_url = attributes["canonical_url"]

    assert product_url.value == (
        "https://shop.example.com/products/cloud-sofa?variant=blue"
    )
    assert canonical_url.value == "https://shop.example.com/products/cloud-sofa"
    assert product_url.field_path == "products[0].url"
    assert canonical_url.field_path == "canonical_url"
    assert product_url.source_record_id == record.id
    assert canonical_url.source_record_id == record.id
    assert product_url.excerpt == raw_product_url
    assert canonical_url.excerpt == raw_canonical_url


def test_url_batch_normalization_is_idempotent() -> None:
    source = _source("csv")
    record = _record(
        source,
        external_id="p-1",
        payload={
            "product_id": "p-1",
            "title": "Cloud Sofa",
            "product_url": "https://EXAMPLE.com:443/cloud-sofa#product",
            "canonical_url": "https://example.com/cloud-sofa#canonical",
        },
    )
    adapted = normalize_source_records(source, [record])

    first = normalize_batch_urls(adapted, source=source, records=[record])
    second = normalize_batch_urls(first, source=source, records=[record])

    assert second == first
    attributes = _attributes(first.products[0])
    assert attributes["product_url"].value == "https://example.com/cloud-sofa"
    assert attributes["canonical_url"].value == "https://example.com/cloud-sofa"
    assert attributes["product_url"].excerpt.endswith("#product")
    assert attributes["canonical_url"].excerpt.endswith("#canonical")


def test_variant_option_order_does_not_change_identity() -> None:
    source = _source("shopify")
    first = _record(
        source,
        external_id="snapshot-1",
        payload=_shopify_payload(
            [
                {"name": "Color", "value": "Blue"},
                {"name": "Size", "value": "Large"},
            ]
        ),
    )
    second = _record(
        source,
        external_id="snapshot-2",
        payload=_shopify_payload(
            [
                {"name": "Size", "value": "Large"},
                {"name": "Color", "value": "Blue"},
            ]
        ),
    )

    first_variant = normalize_source_records(source, [first]).products[0].variants[0]
    second_variant = normalize_source_records(source, [second]).products[0].variants[0]

    assert first_variant.canonical_key == second_variant.canonical_key
    assert first_variant.option_values == second_variant.option_values == {
        "Color": "Blue",
        "Size": "Large",
    }


def test_cross_market_products_remain_separate_but_generate_identity_candidate() -> None:
    gtin = "0123456789012"
    us = _profile(canonical_key="source:us:product:cloud-sofa", gtin=gtin)
    uk = _profile(canonical_key="source:uk:product:cloud-sofa", gtin=gtin)

    proposals = CatalogIdentityService()._proposals([us, uk])
    proposal = proposals[_pair(us.product.id, uk.product.id)]

    assert us.product.canonical_key != uk.product.canonical_key
    assert proposal.match_type == "deterministic"
    assert proposal.score_basis_points == 10000
    assert proposal.signals[0]["kind"] == "gtin_exact"
