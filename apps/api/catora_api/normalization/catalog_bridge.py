from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.normalization.adapters import (
    canonical_product_key,
    canonical_variant_key,
    normalize_key,
    normalize_text,
)
from catora_api.normalization.service import (
    CatalogNormalizationService,
    NormalizationSummary,
    _Counters,
)
from catora_api.normalization.types import (
    JsonScalar,
    JsonValue,
    NormalizationBatch,
    NormalizedAttribute,
    NormalizedImage,
    NormalizedProduct,
    NormalizedVariant,
)
from catora_api.normalization.values import normalize_batch_values


class CatalogBridgeNormalizationPipeline(CatalogNormalizationService):
    async def normalize_job(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
    ) -> NormalizationSummary:
        workspace_id = cast(uuid.UUID, source.workspace_id)
        if workspace_id != job.workspace_id:
            raise ValueError("Source and job belong to different workspaces")
        if source.id != job.catalog_source_id:
            raise ValueError("Job does not belong to source")
        records = (
            await session.scalars(
                select(SourceRecord)
                .where(
                    SourceRecord.workspace_id == workspace_id,
                    SourceRecord.catalog_source_id == source.id,
                    SourceRecord.last_seen_job_id == job.id,
                )
                .order_by(SourceRecord.snapshot_at, SourceRecord.id)
            )
        ).all()
        batch = normalize_batch_values(
            normalize_catalog_bridge_records(source, records),
            source_config=source.config,
        )
        counters = _Counters()
        for candidate in batch.products:
            await self._persist_product(
                session,
                workspace_id=workspace_id,
                candidate=candidate,
                counters=counters,
            )
        await session.commit()
        return counters.summary(rejected_records=len(batch.rejected_record_ids))


def normalize_catalog_bridge_records(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    products: list[NormalizedProduct] = []
    rejected: list[uuid.UUID] = []
    for record in records:
        payload = record.payload
        product_id = _text(payload.get("id"))
        title = normalize_text(payload.get("title"))
        if product_id is None or title is None:
            rejected.append(record.id)
            continue
        variants = _variants(source, record, payload)
        images = _images(source, record, payload, variants)
        products.append(
            NormalizedProduct(
                canonical_key=canonical_product_key(source.id, product_id),
                source_id=product_id,
                title=title,
                source_record_id=record.id,
                title_field_path="title",
                attributes=tuple(_product_attributes(record, payload)),
                variants=tuple(variants),
                images=tuple(images),
            )
        )
    return NormalizationBatch(
        products=tuple(products),
        rejected_record_ids=tuple(rejected),
    )


def _product_attributes(
    record: SourceRecord,
    payload: Mapping[str, Any],
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    fields = (
        ("description", normalize_text(payload.get("description")), "string"),
        ("slug", _text(payload.get("slug")), "string"),
        ("product_url", _text(payload.get("url")), "url"),
        ("canonical_url", _text(payload.get("canonicalUrl")), "url"),
        ("status", _text(payload.get("status")), "string"),
        ("brand", normalize_text(payload.get("brand")), "string"),
        ("product_type", normalize_text(payload.get("productType")), "string"),
    )
    for key, value, value_type in fields:
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type=value_type,
                    field_path=key if key not in {"product_url", "canonical_url"} else (
                        "url" if key == "product_url" else "canonicalUrl"
                    ),
                )
            )
    for key in ("categories", "collections", "tags"):
        values = _string_list(payload.get(key))
        if values:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=values,
                    value_type="list",
                    field_path=key,
                )
            )
    seo = _mapping(payload.get("seo"))
    for key, source_key in (
        ("seo_title", "title"),
        ("seo_description", "description"),
    ):
        value = normalize_text(seo.get(source_key))
        if value is not None:
            attributes.append(
                _attribute(
                    record,
                    key=key,
                    value=value,
                    value_type="string",
                    field_path=f"seo.{source_key}",
                )
            )
    attributes.extend(
        _mapped_attributes(
            record,
            _mapping(payload.get("attributes")),
            prefix="attribute",
            field_path="attributes",
        )
    )
    return attributes


def _variants(
    source: CatalogSource,
    record: SourceRecord,
    payload: Mapping[str, Any],
) -> list[NormalizedVariant]:
    variants: list[NormalizedVariant] = []
    for item in _sequence(payload.get("variants")):
        variant = _mapping(item)
        variant_id = _text(variant.get("id"))
        if variant_id is None:
            continue
        attributes: list[NormalizedAttribute] = []
        for key, source_key, value_type in (
            ("price", "price", "decimal"),
            ("compare_at_price", "compareAtPrice", "decimal"),
            ("currency", "currency", "string"),
            ("availability", "availability", "string"),
        ):
            value = _scalar(variant.get(source_key))
            if value is not None:
                attributes.append(
                    _attribute(
                        record,
                        key=key,
                        value=value,
                        value_type=value_type,
                        field_path=f"variants[{variant_id}].{source_key}",
                    )
                )
        attributes.extend(
            _mapped_attributes(
                record,
                _mapping(variant.get("attributes")),
                prefix="attribute",
                field_path=f"variants[{variant_id}].attributes",
            )
        )
        option_values = {
            normalize_key(key): value
            for key, raw_value in _mapping(variant.get("options")).items()
            if (value := _scalar(raw_value)) is not None
        }
        variants.append(
            NormalizedVariant(
                canonical_key=canonical_variant_key(source.id, variant_id),
                source_id=variant_id,
                source_record_id=record.id,
                sku=_text(variant.get("sku")),
                title=normalize_text(variant.get("title")),
                option_values=option_values,
                attributes=tuple(attributes),
            )
        )
    return variants


def _images(
    source: CatalogSource,
    record: SourceRecord,
    payload: Mapping[str, Any],
    variants: Sequence[NormalizedVariant],
) -> list[NormalizedImage]:
    variant_keys = {variant.source_id: variant.canonical_key for variant in variants}
    images: list[NormalizedImage] = []
    seen: set[tuple[str, str | None]] = set()

    def append_images(items: object, *, variant_id: str | None, path: str) -> None:
        for index, item in enumerate(_sequence(items)):
            image = _mapping(item)
            url = _text(image.get("url"))
            if url is None:
                continue
            linked_variant = _text(image.get("variantId")) or variant_id
            identity = (url, linked_variant)
            if identity in seen:
                continue
            images.append(
                NormalizedImage(
                    url=url,
                    source_record_id=record.id,
                    field_path=f"{path}[{index}].url",
                    alt_text=normalize_text(image.get("altText")),
                    position=_integer(image.get("position"), default=len(images)),
                    variant_key=(
                        variant_keys.get(linked_variant) if linked_variant is not None else None
                    ),
                )
            )
            seen.add(identity)

    append_images(payload.get("images"), variant_id=None, path="images")
    for item in _sequence(payload.get("variants")):
        variant = _mapping(item)
        variant_id = _text(variant.get("id"))
        if variant_id is not None:
            append_images(
                variant.get("images"),
                variant_id=variant_id,
                path=f"variants[{variant_id}].images",
            )
    return images


def _mapped_attributes(
    record: SourceRecord,
    values: Mapping[str, Any],
    *,
    prefix: str,
    field_path: str,
) -> list[NormalizedAttribute]:
    attributes: list[NormalizedAttribute] = []
    for key, raw_value in values.items():
        value, value_type = _json_value(raw_value)
        if value is None:
            continue
        normalized_key = normalize_key(key)
        attributes.append(
            _attribute(
                record,
                key=f"{prefix}.{normalized_key}",
                value=value,
                value_type=value_type,
                field_path=f"{field_path}.{key}",
                confidence="medium",
            )
        )
    return attributes


def _json_value(value: object) -> tuple[JsonValue, str]:
    scalar = _scalar(value)
    if scalar is not None:
        return scalar, _scalar_type(scalar)
    if isinstance(value, list | tuple):
        scalars = [_scalar(item) for item in value]
        if all(item is not None for item in scalars):
            return cast(list[JsonScalar], scalars), "list"
    if isinstance(value, dict):
        mapped = {key: _scalar(item) for key, item in value.items()}
        if all(item is not None for item in mapped.values()):
            return cast(dict[str, JsonScalar], mapped), "object"
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False), "json"
    except (TypeError, ValueError):
        return str(value), "string"


def _attribute(
    record: SourceRecord,
    *,
    key: str,
    value: JsonValue,
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


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast(Sequence[object], value) if isinstance(value, list | tuple) else ()


def _text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _scalar(value: object) -> JsonScalar:
    return value if isinstance(value, str | int | float | bool) else None


def _scalar_type(value: JsonScalar) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    return "string"


def _string_list(value: object) -> list[str]:
    return [text for item in _sequence(value) if (text := _text(item))]


def _integer(value: object, *, default: int) -> int:
    return value if isinstance(value, int) and value >= 0 else default
