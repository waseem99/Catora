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
        if not product_id:
            rejected.append(record.id)
            continue
        grouped[product_id].append(record)

    products: list[NormalizedProduct] = []
    for product_id, product_records in grouped.items():
        first = product_records[0]
        title = next(
            (
                value
                for record in product_records
                if (value := normalize_text(record.payload.get("title")))
            ),
            None,
        )
        if not title:
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
                if value is not None and key not in seen_product_attributes:
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
            if variant_id:
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
            else:
                for attribute in commerce_attributes:
                    if attribute.key not in seen_product_attributes:
                        attributes.append(attribute)
                        seen_product_attributes.add(attribute.key)

        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, product_id),
                source_id=product_id,
                title=title,
                source_record_id=first.id,
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
        if not product_id or not title:
            rejected.append(record.id)
            continue

        attributes: list[NormalizedAttribute] = []
        for key, value, value_type, field_path in (
            ("description", normalize_text(product.get("descriptionHtml")), "string", "product.descriptionHtml"),
            ("vendor", normalize_text(product.get("vendor")), "string", "product.vendor"),
            ("product_type", normalize_text(product.get("productType")), "string", "product.productType"),
            ("status", _string(product.get("status")), "string", "product.status"),
            ("handle", _string(product.get("handle")), "string", "product.handle"),
            ("product_url", _string(product.get("onlineStoreUrl")), "url", "product.onlineStoreUrl"),
        ):
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
        for key, source_key in (("seo_title", "title"), ("seo_description", "description")):
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
        collections = _connection_nodes(product.get("collections"))
        collection_titles = [
            value
            for collection in collections
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
            if not namespace or not field_key or raw_value is None:
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

        variants: list[NormalizedVariant] = []
        images: list[NormalizedImage] = []
        seen_images: set[str] = set()
        for variant in _connection_nodes(product.get("variants")):
            variant_id = _string(variant.get("id"))
            if not variant_id:
                continue
            selected_options = {
                name: value
                for item in _sequence(variant.get("selectedOptions"))
                if (name := _string(_mapping(item).get("name")))
                and (value := _scalar(_mapping(item).get("value"))) is not None
            }
            variant_attributes = _shopify_variant_attributes(record, variant)
            variant_key = canonical_variant_key(source.id, variant_id)
            variants.append(
                NormalizedVariant(
                    canonical_key=variant_key,
                    source_id=variant_id,
                    source_record_id=record.id,
                    sku=_string(variant.get("sku")),
                    title=normalize_text(variant.get("title")),
                    option_values=selected_options,
                    attributes=tuple(variant_attributes),
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

        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, product_id),
                source_id=product_id,
                title=title,
                source_record_id=record.id,
                title_field_path="product.title",
                attributes=tuple(attributes),
                variants=tuple(variants),
                images=tuple(images),
                warnings=record.payload.get("warnings", ())
                if isinstance(record.payload.get("warnings"), tuple)
                else (),
            )
        )
    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(rejected),
    )


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
        title = normalize_text(candidate.get("name")) or normalize_text(fallback.get("title"))
        if not title:
            rejected.append(record.id)
            continue
        attributes: list[NormalizedAttribute] = []
        values = (
            ("description", normalize_text(candidate.get("description")) or normalize_text(fallback.get("description")), "string", "products[0].description"),
            ("product_url", _string(candidate.get("url")) or canonical_url, "url", "canonical_url"),
            ("sku", _string(candidate.get("sku")), "string", "products[0].sku"),
            ("mpn", _string(candidate.get("mpn")), "string", "products[0].mpn"),
            ("gtin", _first_string(candidate, ("gtin", "gtin8", "gtin12", "gtin13", "gtin14")), "string", "products[0].gtin"),
            ("category", normalize_text(candidate.get("category")), "string", "products[0].category"),
        )
        for key, value, value_type, field_path in values:
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
        offers = _first_mapping(candidate.get("offers"))
        attributes.extend(_public_offer_attributes(record, offers))
        attributes.extend(_public_additional_properties(record, candidate))

        images: list[NormalizedImage] = []
        image_values = candidate.get("image") or fallback.get("image")
        for position, image_url in enumerate(_image_urls(image_values)):
            images.append(
                NormalizedImage(
                    url=image_url,
                    source_record_id=record.id,
                    field_path="products[0].image",
                    position=position,
                )
            )

        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, source_id),
                source_id=source_id,
                title=title,
                source_record_id=record.id,
                title_field_path="products[0].name" if candidate else "html_fallback.title",
                attributes=tuple(attributes),
                images=tuple(images),
            )
        )
    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(rejected),
    )


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
    attributes: list[NormalizedAttribute] = []
    fields = (
        ("price", _scalar(variant.get("price")), "decimal"),
        ("compare_at_price", _scalar(variant.get("compareAtPrice")), "decimal"),
        ("available_for_sale", _scalar(variant.get("availableForSale")), "boolean"),
        ("inventory_quantity", _scalar(variant.get("inventoryQuantity")), "integer"),
        ("barcode", _scalar(variant.get("barcode")), "string"),
    )
    for key, value, value_type in fields:
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type=value_type,
                    field_path=f"product.variants.nodes.{key}",
                )
            )
    return attributes


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
    confidence: str = "high",
) -> NormalizedAttribute:
    return NormalizedAttribute(
        key=key,
        value=value,
        value_type=value_type,
        source_record_id=record.id,
        field_path=field_path,
        confidence=cast(Any, confidence),
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
    return (scalar if scalar is not None else str(value), field_type or "string")


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast(Sequence[object], value) if isinstance(value, list | tuple) else ()


def _connection_nodes(value: object) -> list[Mapping[str, Any]]:
    nodes = _mapping(value).get("nodes")
    return [_mapping(item) for item in _sequence(nodes)]


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _scalar(value: object) -> JsonScalar:
    return value if isinstance(value, str | int | float | bool) else None


def _string_list(value: object) -> list[str]:
    return [item for item in _sequence(value) if isinstance(item, str)]


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
        if isinstance(candidate, str):
            url = _string(candidate)
        else:
            url = _string(_mapping(candidate).get("url"))
        if url and url not in urls:
            urls.append(url)
    return urls
