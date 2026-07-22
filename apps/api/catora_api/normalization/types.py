from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | Sequence[JsonScalar] | Mapping[str, JsonScalar]
type Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class NormalizedAttribute:
    key: str
    value: JsonValue
    value_type: str
    source_record_id: uuid.UUID
    field_path: str
    unit: str | None = None
    locale: str | None = None
    confidence: Confidence = "high"
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    url: str
    source_record_id: uuid.UUID
    field_path: str
    alt_text: str | None = None
    position: int = 0
    variant_key: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedVariant:
    canonical_key: str
    source_id: str
    source_record_id: uuid.UUID
    sku: str | None = None
    title: str | None = None
    option_values: Mapping[str, JsonScalar] = field(default_factory=dict)
    attributes: tuple[NormalizedAttribute, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedProduct:
    canonical_key: str
    source_id: str
    title: str
    source_record_id: uuid.UUID
    title_field_path: str
    attributes: tuple[NormalizedAttribute, ...] = ()
    variants: tuple[NormalizedVariant, ...] = ()
    images: tuple[NormalizedImage, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizationBatch:
    products: tuple[NormalizedProduct, ...]
    rejected_record_ids: tuple[uuid.UUID, ...] = ()
    warnings: tuple[str, ...] = ()
