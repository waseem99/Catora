from __future__ import annotations

import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import (
    CatalogSource,
    IngestionJob,
    SourceRecord,
)
from catora_api.normalization.adapters import (
    canonical_product_key,
    normalize_source_records,
)
from catora_api.normalization.service import (
    CatalogNormalizationService,
    NormalizationSummary,
    _Counters,
)
from catora_api.normalization.types import (
    NormalizationBatch,
    NormalizedAttribute,
    NormalizedProduct,
)
from catora_api.normalization.values import normalize_batch_values


class CatalogNormalizationPipeline(CatalogNormalizationService):
    """Production normalization entrypoint with acceptance-level URL behavior."""

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
                    SourceRecord.ingestion_job_id == job.id,
                )
                .order_by(SourceRecord.snapshot_at, SourceRecord.id)
            )
        ).all()
        batch = normalize_batch_values(
            normalize_batch_urls(
                normalize_source_records(source, records),
                source=source,
                records=records,
            ),
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


def normalize_batch_urls(
    batch: NormalizationBatch,
    *,
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> NormalizationBatch:
    replacements = _source_url_attributes(source, records)
    products = tuple(
        _normalize_product_urls(
            product,
            replacements=replacements.get(product.canonical_key, {}),
        )
        for product in batch.products
    )
    return replace(batch, products=products)


def normalize_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = unicodedata.normalize("NFKC", value).strip()
    if not raw or any(character.isspace() for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
        return None

    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if not host:
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    scheme = parsed.scheme.casefold()
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    normalized = SplitResult(
        scheme=scheme,
        netloc=netloc,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def _normalize_product_urls(
    product: NormalizedProduct,
    *,
    replacements: Mapping[str, NormalizedAttribute],
) -> NormalizedProduct:
    attributes: list[NormalizedAttribute] = []
    handled: set[str] = set()
    for attribute in product.attributes:
        replacement = replacements.get(attribute.key)
        if replacement is not None:
            if attribute.key not in handled:
                attributes.append(replacement)
                handled.add(attribute.key)
            continue
        if attribute.value_type == "url":
            attributes.append(_normalized_existing_url(attribute))
        else:
            attributes.append(attribute)
    for key, replacement in replacements.items():
        if key not in handled:
            attributes.append(replacement)
    return replace(product, attributes=tuple(attributes))


def _normalized_existing_url(attribute: NormalizedAttribute) -> NormalizedAttribute:
    raw = attribute.value if isinstance(attribute.value, str) else None
    normalized = normalize_url(raw)
    if normalized is None:
        return replace(
            attribute,
            confidence="low",
            excerpt=raw or attribute.excerpt,
        )
    return replace(
        attribute,
        value=normalized,
        excerpt=raw or attribute.excerpt,
    )


def _source_url_attributes(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> dict[str, dict[str, NormalizedAttribute]]:
    if source.source_type == "csv":
        return _csv_url_attributes(source, records)
    if source.source_type == "shopify":
        return _shopify_url_attributes(source, records)
    if source.source_type in {"sitemap", "urls"}:
        return _public_url_attributes(source, records)
    return {}


def _csv_url_attributes(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> dict[str, dict[str, NormalizedAttribute]]:
    grouped: dict[str, list[SourceRecord]] = defaultdict(list)
    for record in records:
        product_id = _string(record.payload.get("product_id"))
        if product_id:
            grouped[product_id].append(record)

    result: dict[str, dict[str, NormalizedAttribute]] = {}
    for product_id, product_records in grouped.items():
        attributes: dict[str, NormalizedAttribute] = {}
        for key in ("product_url", "canonical_url"):
            for record in product_records:
                raw = _string(record.payload.get(key))
                if raw is None:
                    continue
                attributes[key] = _url_attribute(
                    record,
                    key=key,
                    raw=raw,
                    field_path=f"payload.{key}",
                )
                break
        if attributes:
            result[canonical_product_key(source.id, product_id)] = attributes
    return result


def _shopify_url_attributes(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> dict[str, dict[str, NormalizedAttribute]]:
    result: dict[str, dict[str, NormalizedAttribute]] = {}
    for record in records:
        product = _mapping(record.payload.get("product"))
        product_id = _string(product.get("id"))
        if product_id is None:
            continue
        attributes: dict[str, NormalizedAttribute] = {}
        product_url = _string(product.get("onlineStoreUrl"))
        if product_url:
            attributes["product_url"] = _url_attribute(
                record,
                key="product_url",
                raw=product_url,
                field_path="product.onlineStoreUrl",
            )
        canonical_url = _string(product.get("canonicalUrl")) or _string(
            record.payload.get("canonical_url")
        )
        if canonical_url:
            attributes["canonical_url"] = _url_attribute(
                record,
                key="canonical_url",
                raw=canonical_url,
                field_path=(
                    "product.canonicalUrl"
                    if _string(product.get("canonicalUrl"))
                    else "canonical_url"
                ),
            )
        if attributes:
            result[canonical_product_key(source.id, product_id)] = attributes
    return result


def _public_url_attributes(
    source: CatalogSource,
    records: Sequence[SourceRecord],
) -> dict[str, dict[str, NormalizedAttribute]]:
    result: dict[str, dict[str, NormalizedAttribute]] = {}
    for record in records:
        candidates = [
            _mapping(value) for value in _sequence(record.payload.get("products"))
        ]
        candidate = candidates[0] if candidates else {}
        raw_canonical_url = _string(record.payload.get("canonical_url"))
        source_id = (
            _string(candidate.get("@id"))
            or _string(candidate.get("sku"))
            or _string(candidate.get("mpn"))
            or raw_canonical_url
            or record.external_id
        )
        candidate_url = _string(candidate.get("url"))
        raw_product_url = candidate_url or record.external_id
        canonical_url = raw_canonical_url or raw_product_url
        result[canonical_product_key(source.id, source_id)] = {
            "product_url": _url_attribute(
                record,
                key="product_url",
                raw=raw_product_url,
                field_path="products[0].url" if candidate_url else "external_id",
            ),
            "canonical_url": _url_attribute(
                record,
                key="canonical_url",
                raw=canonical_url,
                field_path="canonical_url" if raw_canonical_url else (
                    "products[0].url" if candidate_url else "external_id"
                ),
            ),
        }
    return result


def _url_attribute(
    record: SourceRecord,
    *,
    key: str,
    raw: str,
    field_path: str,
) -> NormalizedAttribute:
    normalized = normalize_url(raw)
    return NormalizedAttribute(
        key=key,
        value=normalized or raw,
        value_type="url",
        source_record_id=record.id,
        field_path=field_path,
        confidence="high" if normalized else "low",
        excerpt=raw,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return value
    return ()


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
