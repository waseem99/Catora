from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorValidation,
)
from catora_api.schemas.service_visibility import WordPressSnapshotBatch
from catora_api.storage import ObjectStorage


class WordPressSnapshotConnector(CatalogConnector):
    source_type = "wordpress"
    capabilities = ConnectorCapabilities(
        supports_incremental_sync=False,
        supports_resume=True,
        supports_schema_discovery=True,
        supports_remote_validation=False,
    )

    def __init__(self, *, config: Mapping[str, Any], storage: ObjectStorage) -> None:
        self.config = config
        self.storage = storage

    def _snapshot(self) -> Mapping[str, Any]:
        value = self.config.get("service_visibility_snapshot")
        return value if isinstance(value, dict) else {}

    async def validate(self) -> ConnectorValidation:
        snapshot = self._snapshot()
        if snapshot.get("status") != "complete":
            return ConnectorValidation(
                valid=False,
                errors=("WordPress snapshot is not complete",),
            )
        batches = snapshot.get("batches")
        if not isinstance(batches, list):
            return ConnectorValidation(valid=False, errors=("WordPress batches are missing",))
        return ConnectorValidation(
            valid=True,
            discovered_fields=(
                "url",
                "canonical_url",
                "title",
                "meta_description",
                "headings",
                "links",
                "visible_text",
                "json_ld",
                "wordpress",
            ),
        )

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        snapshot = self._snapshot()
        batches_value = snapshot.get("batches")
        batches = (
            [item for item in batches_value if isinstance(item, dict)]
            if isinstance(batches_value, list)
            else []
        )
        start = int((checkpoint or {}).get("batch_sequence", 0))
        for sequence, batch_meta in enumerate(batches[start:], start=start):
            object_key = batch_meta.get("object_key")
            checksum = batch_meta.get("checksum")
            if not isinstance(object_key, str) or not isinstance(checksum, str):
                raise ValueError("WordPress batch metadata is invalid")
            content = await self.storage.get_bytes(object_key)
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError("WordPress batch checksum does not match")
            batch = WordPressSnapshotBatch.model_validate_json(content)
            records: list[ConnectorRecord] = []
            for item in batch.records:
                payload = item.model_dump(mode="json")
                canonical = item.canonical_url or item.url
                stable = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                records.append(
                    ConnectorRecord(
                        external_id=canonical,
                        record_type="service_page",
                        payload=payload,
                        content_hash=hashlib.sha256(stable.encode()).hexdigest(),
                        source_updated_at=item.source_updated_at,
                    )
                )
            yield ConnectorPage(
                records=tuple(records),
                rejections=(),
                next_checkpoint={"batch_sequence": sequence + 1},
            )
