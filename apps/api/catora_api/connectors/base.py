from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    supports_incremental_sync: bool = False
    supports_resume: bool = True
    supports_schema_discovery: bool = False
    supports_remote_validation: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    discovered_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectorRecord:
    external_id: str
    record_type: str
    payload: Mapping[str, Any]
    content_hash: str
    source_updated_at: datetime | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectorRejection:
    row_number: int | None
    reason: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorPage:
    records: tuple[ConnectorRecord, ...]
    rejections: tuple[ConnectorRejection, ...]
    next_checkpoint: Mapping[str, Any] | None


class CatalogConnector(ABC):
    source_type: str
    capabilities: ConnectorCapabilities

    @abstractmethod
    async def validate(self) -> ConnectorValidation:
        """Validate configuration and report discoverable schema details."""

    @abstractmethod
    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        """Yield deterministic pages that can be persisted and resumed."""
