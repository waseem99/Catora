from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorValidation,
)
from catora_api.schemas.catalog_bridge import (
    CATALOG_BRIDGE_PROTOCOL_VERSION,
    CatalogBridgeBatch,
)
from catora_api.schemas.restaurant_bridge import (
    RESTAURANT_BRIDGE_PROFILE,
    RestaurantBridgeBatch,
)
from catora_api.storage import ObjectStorage


class CatalogBridgeConnector(CatalogConnector):
    source_type = "bridge"
    capabilities = ConnectorCapabilities(
        supports_incremental_sync=False,
        supports_resume=True,
        supports_schema_discovery=False,
        supports_remote_validation=True,
    )

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        storage: ObjectStorage,
    ) -> None:
        self._config = config
        self._storage = storage

    def _profile(self) -> str:
        value = self._config.get("profile")
        return value if isinstance(value, str) else "catalog/v1"

    def _snapshot(self) -> Mapping[str, Any]:
        snapshot = self._config.get("bridge_snapshot")
        return snapshot if isinstance(snapshot, dict) else {}

    def _batches(self) -> list[Mapping[str, Any]]:
        batches = self._snapshot().get("batches")
        if not isinstance(batches, list):
            return []
        return [item for item in batches if isinstance(item, dict)]

    async def validate(self) -> ConnectorValidation:
        snapshot = self._snapshot()
        errors: list[str] = []
        if snapshot.get("protocol_version") != CATALOG_BRIDGE_PROTOCOL_VERSION:
            errors.append("Catalog bridge snapshot protocol is unsupported")
        if snapshot.get("status") != "complete":
            errors.append("Catalog bridge snapshot is not complete")
        profile = self._profile()
        if profile not in {"catalog/v1", RESTAURANT_BRIDGE_PROFILE}:
            errors.append("Catalog bridge profile is unsupported")
        if profile == RESTAURANT_BRIDGE_PROFILE and snapshot.get("profile") != profile:
            errors.append("Restaurant bridge snapshot profile is missing")
        batches = self._batches()
        if not batches:
            errors.append("Catalog bridge snapshot has no batches")
        sequences = [item.get("sequence") for item in batches]
        if sequences != list(range(len(batches))):
            errors.append("Catalog bridge batch sequences are incomplete")
        for batch in batches:
            if not isinstance(batch.get("object_key"), str):
                errors.append("Catalog bridge batch object is missing")
                break
            if not isinstance(batch.get("checksum"), str):
                errors.append("Catalog bridge batch checksum is missing")
                break
        discovered_fields = (
            (
                "recordType",
                "id",
                "name",
                "locations",
                "menus",
                "offers",
            )
            if profile == RESTAURANT_BRIDGE_PROFILE
            else (
                "id",
                "title",
                "description",
                "variants",
                "images",
                "attributes",
                "seo",
            )
        )
        return ConnectorValidation(
            valid=not errors,
            errors=tuple(errors),
            discovered_fields=discovered_fields,
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
        start_sequence = int((checkpoint or {}).get("batch_sequence", 0))
        profile = self._profile()
        for metadata in self._batches():
            sequence = metadata.get("sequence")
            if not isinstance(sequence, int) or sequence < start_sequence:
                continue
            object_key = metadata.get("object_key")
            checksum = metadata.get("checksum")
            if not isinstance(object_key, str) or not isinstance(checksum, str):
                raise ValueError("Catalog bridge batch metadata is invalid")
            content = await self._storage.get_bytes(object_key)
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError(f"Catalog bridge batch {sequence} checksum mismatch")
            try:
                payload = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Catalog bridge batch {sequence} is not valid JSON") from exc
            if profile == RESTAURANT_BRIDGE_PROFILE:
                restaurant_batch = RestaurantBridgeBatch.model_validate(payload)
                if restaurant_batch.sequence != sequence:
                    raise ValueError(f"Catalog bridge batch {sequence} sequence mismatch")
                records = tuple(
                    self._record(
                        brand.model_dump(mode="json", by_alias=True, exclude_none=True),
                        record_type="restaurant_brand",
                    )
                    for brand in restaurant_batch.records
                )
            else:
                catalog_batch = CatalogBridgeBatch.model_validate(payload)
                if catalog_batch.sequence != sequence:
                    raise ValueError(f"Catalog bridge batch {sequence} sequence mismatch")
                records = tuple(
                    self._record(
                        product.model_dump(mode="json", by_alias=True, exclude_none=True),
                        record_type="product",
                    )
                    for product in catalog_batch.records
                )
            yield ConnectorPage(
                records=records,
                rejections=(),
                next_checkpoint={"batch_sequence": sequence + 1},
            )

    @staticmethod
    def _record(payload: dict[str, Any], *, record_type: str) -> ConnectorRecord:
        stable_payload = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        updated_value = payload.get("updatedAt")
        source_updated_at = None
        if isinstance(updated_value, str):
            source_updated_at = datetime.fromisoformat(updated_value.replace("Z", "+00:00"))
        return ConnectorRecord(
            external_id=str(payload["id"]),
            record_type=record_type,
            payload=payload,
            content_hash=hashlib.sha256(stable_payload.encode()).hexdigest(),
            source_updated_at=source_updated_at,
        )
