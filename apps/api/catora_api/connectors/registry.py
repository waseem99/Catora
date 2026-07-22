from __future__ import annotations

from collections.abc import Callable

from catora_api.connectors.base import CatalogConnector

ConnectorFactory = Callable[..., CatalogConnector]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, source_type: str, factory: ConnectorFactory) -> None:
        normalized = source_type.strip().lower()
        if not normalized:
            raise ValueError("source_type is required")
        if normalized in self._factories:
            raise ValueError(f"Connector '{normalized}' is already registered")
        self._factories[normalized] = factory

    def create(self, source_type: str, **kwargs: object) -> CatalogConnector:
        normalized = source_type.strip().lower()
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            raise KeyError(f"Unsupported connector '{normalized}'") from exc
        return factory(**kwargs)

    @property
    def source_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
