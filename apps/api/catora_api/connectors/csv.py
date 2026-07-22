from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, fields
from typing import Any

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorRejection,
    ConnectorValidation,
)


@dataclass(frozen=True, slots=True)
class CsvMapping:
    product_id: str
    title: str
    variant_id: str | None = None
    sku: str | None = None
    description: str | None = None
    product_url: str | None = None
    price: str | None = None
    currency: str | None = None
    availability: str | None = None
    category: str | None = None
    image_url: str | None = None

    def configured_columns(self) -> tuple[str, ...]:
        return tuple(
            value
            for field_info in fields(self)
            if (value := getattr(self, field_info.name))
        )


class CsvCatalogConnector(CatalogConnector):
    source_type = "csv"
    capabilities = ConnectorCapabilities(
        supports_incremental_sync=False,
        supports_resume=True,
        supports_schema_discovery=True,
        supports_remote_validation=False,
    )

    def __init__(
        self,
        *,
        content: bytes | str,
        mapping: CsvMapping,
        encoding: str = "utf-8-sig",
        delimiter: str | None = None,
    ) -> None:
        self._content = content
        self._mapping = mapping
        self._encoding = encoding
        self._delimiter = delimiter

    @property
    def mapping(self) -> CsvMapping:
        return self._mapping

    def _text(self) -> str:
        if isinstance(self._content, str):
            return self._content
        return self._content.decode(self._encoding)

    def _reader(self) -> csv.DictReader[str]:
        text = self._text()
        delimiter = self._delimiter
        if delimiter is None:
            sample = text[:8192]
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        return csv.DictReader(io.StringIO(text), delimiter=delimiter)

    async def validate(self) -> ConnectorValidation:
        try:
            reader = self._reader()
        except UnicodeDecodeError as exc:
            return ConnectorValidation(valid=False, errors=(f"Unable to decode CSV: {exc}",))

        fields_found = tuple(reader.fieldnames or ())
        errors: list[str] = []
        if not fields_found:
            errors.append("CSV must contain a header row")

        for required in (self._mapping.product_id, self._mapping.title):
            if required not in fields_found:
                errors.append(f"Mapped column '{required}' is missing")

        missing_optional = [
            column for column in self._mapping.configured_columns() if column not in fields_found
        ]
        warnings = tuple(
            f"Mapped optional column '{column}' is missing" for column in missing_optional
        )
        return ConnectorValidation(
            valid=not errors,
            errors=tuple(errors),
            warnings=warnings,
            discovered_fields=fields_found,
        )

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")

        validation = await self.validate()
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))

        start_row = int((checkpoint or {}).get("row", 0))
        records: list[ConnectorRecord] = []
        rejections: list[ConnectorRejection] = []
        processed_since_page = 0
        last_row = start_row

        for row_number, row in enumerate(self._reader(), start=1):
            if row_number <= start_row:
                continue
            last_row = row_number
            processed_since_page += 1
            record, rejection = self._convert(row, row_number)
            if record is not None:
                records.append(record)
            if rejection is not None:
                rejections.append(rejection)

            if processed_since_page >= page_size:
                yield ConnectorPage(
                    records=tuple(records),
                    rejections=tuple(rejections),
                    next_checkpoint={"row": row_number},
                )
                records = []
                rejections = []
                processed_since_page = 0

        if records or rejections:
            yield ConnectorPage(
                records=tuple(records),
                rejections=tuple(rejections),
                next_checkpoint={"row": last_row},
            )

    def _convert(
        self, row: Mapping[str, str | None], row_number: int
    ) -> tuple[ConnectorRecord | None, ConnectorRejection | None]:
        product_id = (row.get(self._mapping.product_id) or "").strip()
        title = (row.get(self._mapping.title) or "").strip()
        if not product_id:
            return None, ConnectorRejection(row_number, "Missing product identifier", dict(row))
        if not title:
            return None, ConnectorRejection(row_number, "Missing product title", dict(row))

        payload: dict[str, Any] = {
            "product_id": product_id,
            "title": title,
            "variant_id": self._value(row, self._mapping.variant_id),
            "sku": self._value(row, self._mapping.sku),
            "description": self._value(row, self._mapping.description),
            "product_url": self._value(row, self._mapping.product_url),
            "price": self._value(row, self._mapping.price),
            "currency": self._value(row, self._mapping.currency),
            "availability": self._value(row, self._mapping.availability),
            "category": self._value(row, self._mapping.category),
            "image_url": self._value(row, self._mapping.image_url),
            "raw": dict(row),
        }
        stable_payload = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        content_hash = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()
        variant_id = payload["variant_id"]
        external_id = f"{product_id}:{variant_id}" if variant_id else product_id
        return (
            ConnectorRecord(
                external_id=external_id,
                record_type="product_variant" if variant_id else "product",
                payload=payload,
                content_hash=content_hash,
            ),
            None,
        )

    @staticmethod
    def _value(row: Mapping[str, str | None], column: str | None) -> str | None:
        if column is None:
            return None
        value = row.get(column)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
