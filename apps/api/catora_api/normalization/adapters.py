from __future__ import annotations

import html
import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from typing import Any, cast

from catora_api.db.models.catalog import CatalogSource, SourceRecord
from catora_api.normalization.types import (
    Confidence,
    JsonScalar,
    NormalizationBatch,
    NormalizedAttribute,
    NormalizedImage,
    NormalizedProduct,
    NormalizedVariant,
)

_KEY_PATTERN = re.compile(r"[^a-z0-9]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = _WHITESPACE_PATTERN.sub(" ", data).strip()
        if text:
            self.parts.append(text)


def normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", html.unescape(value))
    if "<" in normalized and ">" in normalized:
        parser = _TextExtractor()
        parser.feed(normalized)
        normalized = " ".join(parser.parts)
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip()
    return normalized or None


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _KEY_PATTERN.sub("_", normalized.lower()).strip("_") or "field"


def canonical_product_key(source_id: uuid.UUID, source_product_id: str) -> str:
    return f"source:{source_id}:product:{source_product_id}"


def canonical_variant_key(source_id: uuid.UUID, source_variant_id: str) -> str:
    return f"source:{source_id}:variant:{source_variant_id}"


def normalize_source_records(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    if source.source_type == "csv":
        return _normalize_csv(source, records)
    if source.source_type == "shopify":
        return _normalize_shopify(source, records)
    if source.source_type in {"sitemap", "urls"}:
        return _normalize_public(source, records)
    return NormalizationBatch(
        products=(),
        rejected_record_ids=tuple(record.id for record in records),
        warnings=(f"unsupported_source_type:{source.source_type}",),
    )


def _normalize_csv(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    grouped: dict[str, list[SourceRecord]] = defaultdict(list)
    rejected: list[uuid.UUID] = []
    for record in records:
        product_id = _string(record.payload.get("product_id"))
        if product_id is None:
            rejected.append(record.id)
            continue
        grouped[product_id].append(record)

    products: list[NormalizedProduct] = []
    for product_id, product_records in grouped.items():
        title = next(
            (
                value
                for record in product_records
                if (value := normalize_text(record.payload.get("title")))
            ),
            None,
        )
        if title is None:
            rejected.extend(record.id for record in product_records)
            continue

        attributes: list[NormalizedAttribute] = []
        variants: list[NormalizedVariant] = []
        images: list[NormalizedImage] = []
        seen_product_attributes: set[str] = set()
        seen_variants: set[str] = set()
        seen_images: set[str] = set()

        for record in product_records:
            payload = record.payload
            variant_id = _string(payload.get("variant_id"))
            product_values = {
                "description": normalize_text(payload.get("description")),
                "product_url": _string(payload.get("product_url")),
                "category": normalize_text(payload.get("category")),
            }
            for key, value in product_values.items():
                if value is None or key in seen_product_attributes:
                    continue
                attributes.append(
                    _attribute(
                        record,
                        key=key,
                        value=value,
                        value_type="url" if key == "product_url" else "string",
                        field_path=f"payload.{key}",
                    )
                )
                seen_product_attributes.add(key)

            image_url = _string(payload.get("image_url"))
            if image_url and image_url not in seen_images:
                images.append(
                    NormalizedImage(
                        url=image_url,
                        source_record_id=record.id,
                        field_path="payload.image_url",
                        position=len(images),
                        variant_key=(
                            canonical_variant_key(source.id, variant_id)
                            if variant_id
                            else None
                        ),
                    )
                )
                seen_images.add(image_url)

            commerce_attributes = _commerce_attributes(record, payload)
            if variant_id is None:
                for attribute in commerce_attributes:
                    if attribute.key not in seen_product_attributes:
                        attributes.append(attribute)
                        seen_product_attributes.add(attribute.key)
                continue

            variant_key = canonical_variant_key(source.id, variant_id)
            if variant_key in seen_variants:
                continue
            variants.append(
                NormalizedVariant(
                    canonical_key=variant_key,
                    source_id=variant_id,
                    source_record_id=record.id,
                    sku=_string(payload.get("sku")),
                    title=_string(payload.get("sku")),
                    attributes=tuple(commerce_attributes),
                )
            )
            seen_variants.add(variant_key)

        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, product_id),
                source_id=product_id,
                title=title,
                source_record_id=product_records[0].id,
                title_field_path="payload.title",
                attributes=tuple(attributes),
                variants=tuple(variants),
                images=tuple(images),
            )
        )

    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(dict.fromkeys(rejected)),
    )


def _normalize_shopify(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    products: list[NormalizedProduct] = []
    rejected: list[uuid.UUID] = []
    for record in records:
        product = _mapping(record.payload.get("product"))
        product_id = _string(product.get("id"))
        title = normalize_text(product.get("title"))
        if product_id is None or title is None:
            rejected.append(record.id)
            continue

        attributes = _shopify_product_attributes(record, product)
        variants, variant_images = _shopify_variants(source, record, product)
        product_images = _shopify_product_images(record, product, variant_images)
        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, product_id),
                source_id=product_id,
                title=title,
                source_record_id=record.id,
                title_field_path="product.title",
                attributes=tuple(attributes),
                variants=tuple(variants),
                images=tuple(product_images),
                warnings=_string_tuple(record.payload.get("warnings")),
            )
        )

    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(rejected),
    )


def _shopify_product_attributes(
    record: SourceRecord,
    product: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    fields = (
        (
            "description",
            normalize_text(product.get("descriptionHtml")),
            "string",
            "product.descriptionHtml",
        ),
        ("vendor", normalize_text(product.get("vendor")), "string", "product.vendor"),
        (
            "product_type",
            normalize_text(product.get("productType")),
            "string",
            "product.productType",
        ),
        ("status", _string(product.get("status")), "string", "product.status"),
        ("handle", _string(product.get("handle")), "string", "product.handle"),
        (
            "product_url",
            _string(product.get("onlineStoreUrl")),
            "url",
            "product.onlineStoreUrl",
        ),
    )
    for key, value, value_type, field_path in fields:
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type=value_type,
                    field_path=field_path,
                )
            )

    tags = _string_list(product.get("tags"))
    if tags:
        attributes.append(
            _attribute(
                record,
                key="tags",
                value=tags,
                value_type="list",
                field_path="product.tags",
            )
        )

    seo = _mapping(product.get("seo"))
    for key, source_key in (
        ("seo_title", "title"),
        ("seo_description", "description"),
    ):
        value = normalize_text(seo.get(source_key))
        if value:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type="string",
                    field_path=f"product.seo.{source_key}",
                )
            )

    collection_titles = [
        value
        for collection in _connection_nodes(product.get("collections"))
        if (value := normalize_text(collection.get("title")))
    ]
    if collection_titles:
        attributes.append(
            _attribute(
                record,
                key="collections",
                value=collection_titles,
                value_type="list",
                field_path="product.collections.nodes",
            )
        )

    for metafield in _connection_nodes(product.get("metafields")):
        namespace = _string(metafield.get("namespace"))
        field_key = _string(metafield.get("key"))
        raw_value = metafield.get("value")
        if namespace is None or field_key is None or raw_value is None:
            continue
        normalized_value, value_type = _shopify_metafield_value(
            raw_value,
            _string(metafield.get("type")),
        )
        attributes.append(
            _attribute(
                record,
                key=f"metafield.{normalize_key(namespace)}.{normalize_key(field_key)}",
                value=normalized_value,
                value_type=value_type,
                field_path=(
                    f"product.metafields.nodes[{namespace}.{field_key}].value"
                ),
            )
        )
    return attributes


def _shopify_variants(
    source: CatalogSource,
    record: SourceRecord,
    product: Mapping[str, Any],
) -> tuple[list[NormalizedVariant], list[NormalizedImage]]:
    variants: list[NormalizedVariant] = []
    images: list[NormalizedImage] = []
    seen_images: set[str] = set()
    for variant in _connection_nodes(product.get("variants")):
        variant_id = _string(variant.get("id"))
        if variant_id is None:
            continue
        option_values = {
            name: value
            for item in _sequence(variant.get("selectedOptions"))
            if (name := _string(_mapping(item).get("name")))
            and (value := _scalar(_mapping(item).get("value"))) is not None
        }
        variant_key = canonical_variant_key(source.id, variant_id)
        variants.append(
            NormalizedVariant(
                canonical_key=variant_key,
                source_id=variant_id,
                source_record_id=record.id,
                sku=_string(variant.get("sku")),
                title=normalize_text(variant.get("title")),
                option_values=option_values,
                attributes=tuple(_shopify_variant_attributes(record, variant)),
            )
        )

        image = _mapping(variant.get("image"))
        image_url = _string(image.get("url"))
        if image_url and image_url not in seen_images:
            images.append(
                NormalizedImage(
                    url=image_url,
                    source_record_id=record.id,
                    field_path="product.variants.nodes.image.url",
                    alt_text=normalize_text(image.get("altText")),
                    position=len(images),
                    variant_key=variant_key,
                )
            )
            seen_images.add(image_url)
    return variants, images


def _shopify_product_images(
    record: SourceRecord,
    product: Mapping[str, Any],
    variant_images: list[NormalizedImage],
) -> list[NormalizedImage]:
    images = list(variant_images)
    seen_images = {image.url for image in images}
    for media in _connection_nodes(product.get("media")):
        image = _mapping(media.get("image"))
        image_url = _string(image.get("url"))
        if image_url and image_url not in seen_images:
            images.append(
                NormalizedImage(
                    url=image_url,
                    source_record_id=record.id,
                    field_path="product.media.nodes.image.url",
                    alt_text=normalize_text(media.get("alt")),
                    position=len(images),
                )
            )
            seen_images.add(image_url)
    return images


def _normalize_public(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    products: list[NormalizedProduct] = []
    rejected: list[uuid.UUID] = []
    for record in records:
        candidates = [
            _mapping(value) for value in _sequence(record.payload.get("products"))
        ]
        candidate = candidates[0] if candidates else {}
        fallback = _mapping(record.payload.get("html_fallback"))
        canonical_url = _string(record.payload.get("canonical_url")) or record.external_id
        source_id = (
            _string(candidate.get("@id"))
            or _string(candidate.get("sku"))
            or _string(candidate.get("mpn"))
            or canonical_url
        )
        title = normalize_text(candidate.get("name")) or normalize_text(
            fallback.get("title")
        )
        if title is None:
            rejected.append(record.id)
            continue

        attributes = _public_product_attributes(
            record,
            candidate=candidate,
            fallback=fallback,
            canonical_url=canonical_url,
        )
        image_values = candidate.get("image") or fallback.get("image")
        images = [
            NormalizedImage(
                url=image_url,
                source_record_id=record.id,
                field_path="products[0].image",
                position=position,
            )
            for position, image_url in enumerate(_image_urls(image_values))
        ]
        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, source_id),
                source_id=source_id,
                title=title,
                source_record_id=record.id,
                title_field_path=(
                    "products[0].name" if candidate else "html_fallback.title"
                ),
                attributes=tuple(attributes),
                images=tuple(images),
            )
        )

    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(rejected),
    )


def _public_product_attributes(
    record: SourceRecord,
    *,
    candidate: Mapping[str, Any],
    fallback: Mapping[str, Any],
    canonical_url: str,
) -> list[NormalizedAttribute]:
    description = normalize_text(candidate.get("description")) or normalize_text(
        fallback.get("description")
    )
    gtin = _first_string(
        candidate,
        ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"),
    )
    values = (
        ("description", description, "string", "products[0].description"),
        (
            "product_url",
            _string(candidate.get("url")) or canonical_url,
            "url",
            "canonical_url",
        ),
        ("sku", _string(candidate.get("sku")), "string", "products[0].sku"),
        ("mpn", _string(candidate.get("mpn")), "string", "products[0].mpn"),
        ("gtin", gtin, "string", "products[0].gtin"),
        (
            "category",
            normalize_text(candidate.get("category")),
            "string",
            "products[0].category",
        ),
    )
    attributes = [
        _attribute(
            record,
            key=key,
            value=value,
            value_type=value_type,
            field_path=field_path,
        )
        for key, value, value_type, field_path in values
        if value is not None
    ]

    brand = candidate.get("brand")
    brand_name = (
        normalize_text(_mapping(brand).get("name"))
        if isinstance(brand, dict)
        else normalize_text(brand)
    )
    if brand_name:
        attributes.append(
            _attribute(
                record,
                key="brand",
                value=brand_name,
                value_type="string",
                field_path="products[0].brand",
            )
        )
    attributes.extend(_public_offer_attributes(record, _first_mapping(candidate.get("offers"))))
    attributes.extend(_public_additional_properties(record, candidate))
    return attributes


def _commerce_attributes(
    record: SourceRecord,
    payload: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    for key, value_type in (
        ("price", "decimal"),
        ("currency", "string"),
        ("availability", "string"),
    ):
        value = _scalar(payload.get(key))
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type=value_type,
                    field_path=f"payload.{key}",
                )
            )
    return attributes


def _shopify_variant_attributes(
    record: SourceRecord,
    variant: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    fields = (
        ("price", _scalar(variant.get("price")), "decimal"),
        ("compare_at_price", _scalar(variant.get("compareAtPrice")), "decimal"),
        (
            "available_for_sale",
            _scalar(variant.get("availableForSale")),
            "boolean",
        ),
        (
            "inventory_quantity",
            _scalar(variant.get("inventoryQuantity")),
            "integer",
        ),
        ("barcode", _scalar(variant.get("barcode")), "string"),
    )
    return [
        _attribute(
            record,
            key=key,
            value=value,
            value_type=value_type,
            field_path=f"product.variants.nodes.{key}",
        )
        for key, value, value_type in fields
        if value is not None
    ]


def _public_offer_attributes(
    record: SourceRecord,
    offer: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    for key, source_key, value_type in (
        ("price", "price", "decimal"),
        ("currency", "priceCurrency", "string"),
        ("availability", "availability", "url"),
    ):
        value = _scalar(offer.get(source_key))
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type=value_type,
                    field_path=f"products[0].offers.{source_key}",
                )
            )
    return attributes


def _public_additional_properties(
    record: SourceRecord,
    product: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    for item in _sequence(product.get("additionalProperty")):
        property_value = _mapping(item)
        name = normalize_text(property_value.get("name"))
        value = _scalar(property_value.get("value"))
        if name and value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=f"additional.{normalize_key(name)}",
                    value=value,
                    value_type="string",
                    field_path=f"products[0].additionalProperty.{name}",
                    confidence="medium",
                )
            )
    return attributes


def _attribute(
    record: SourceRecord,
    *,
    key: str,
    value: JsonScalar | list[JsonScalar] | dict[str, JsonScalar],
    value_type: str,
    field_path: str,
    confidence: Confidence = "high",
) -> NormalizedAttribute:
    return NormalizedAttribute(
        key=key,
        value=value,
        value_type=value_type,
        source_record_id=record.id,
        field_path=field_path,
        confidence=confidence,
        excerpt=str(value)[:500],
    )


def _shopify_metafield_value(
    value: object,
    field_type: str | None,
) -> tuple[JsonScalar, str]:
    if field_type == "boolean" and isinstance(value, str):
        return value.lower() == "true", "boolean"
    if field_type in {"number_integer", "number_decimal"} and isinstance(value, str):
        try:
            return (
                int(value) if field_type == "number_integer" else float(value),
                "integer" if field_type == "number_integer" else "decimal",
            )
        except ValueError:
            return value, "string"
    scalar = _scalar(value)
    return scalar if scalar is not None else str(value), field_type or "string"


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast(Sequence[object], value) if isinstance(value, list | tuple) else ()


def _connection_nodes(value: object) -> list[Mapping[str, Any]]:
    return [_mapping(item) for item in _sequence(_mapping(value).get("nodes"))]


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _scalar(value: object) -> JsonScalar:
    return value if isinstance(value, str | int | float | bool) else None


def _string_list(value: object) -> list[str]:
    return [text for item in _sequence(value) if (text := _string(item))]


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(_string_list(value))


def _first_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, dict):
        return _mapping(value)
    for item in _sequence(value):
        mapping = _mapping(item)
        if mapping:
            return mapping
    return {}


def _first_string(product: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = _string(product.get(key))
        if value:
            return value
    return None


def _image_urls(value: object) -> list[str]:
    candidates = _sequence(value) if isinstance(value, list | tuple) else (value,)
    urls: list[str] = []
    for candidate in candidates:
        url = (
            _string(candidate)
            if isinstance(candidate, str)
            else _string(_mapping(candidate).get("url"))
        )
        if url and url not in urls:
            urls.append(url)
    return urls
