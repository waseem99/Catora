from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from catora_api.connectors.base import CatalogConnector
from catora_api.connectors.csv import CsvCatalogConnector, CsvMapping
from catora_api.db.models.catalog import CatalogSource
from catora_api.storage import ObjectStorage


async def connector_for_source(source: CatalogSource, storage: ObjectStorage) -> CatalogConnector:
    if source.source_type != "csv":
        raise ValueError(f"Unsupported source type '{source.source_type}'")
    config: Mapping[str, Any] = source.config
    object_key = config.get("object_key")
    mapping = config.get("mapping")
    if not isinstance(object_key, str) or not object_key:
        raise ValueError("CSV source object_key is missing")
    if not isinstance(mapping, dict):
        raise ValueError("CSV source mapping is missing")
    content = await storage.get_bytes(object_key)
    delimiter = config.get("delimiter")
    return CsvCatalogConnector(
        content=content,
        mapping=CsvMapping(**mapping),
        encoding=str(config.get("encoding") or "utf-8-sig"),
        delimiter=delimiter if isinstance(delimiter, str) else None,
    )
