from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

DuplicateFailureCode = Literal[
    "title_exact_duplicate",
    "title_near_duplicate",
    "description_exact_duplicate",
    "description_near_duplicate",
]

_WHITESPACE_PATTERN = re.compile(r"\s+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SIMHASH_BITS = 64
_SIMHASH_BAND_BITS = 16
_SIMHASH_BANDS = _SIMHASH_BITS // _SIMHASH_BAND_BITS
_SIMHASH_MAX_DISTANCE = 3
_MAX_PEER_SAMPLES = 20


@dataclass(frozen=True, slots=True)
class DuplicateContentRecord:
    product_id: uuid.UUID
    category_key: str
    title: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class DuplicateContentResult:
    product_id: uuid.UUID
    failure_codes: tuple[DuplicateFailureCode, ...]
    peer_samples: tuple[uuid.UUID, ...]
    match_counts: Mapping[DuplicateFailureCode, int]

    def payload(self) -> dict[str, object]:
        return {
            "failure_codes": list(self.failure_codes),
            "peer_product_ids": [str(item) for item in self.peer_samples],
            "match_counts": {
                key: self.match_counts[key] for key in sorted(self.match_counts)
            },
        }


@dataclass(frozen=True, slots=True)
class _FieldPlan:
    field_name: Literal["title", "description"]
    exact_code: DuplicateFailureCode
    near_code: DuplicateFailureCode
    minimum_chars: int
    minimum_tokens: int
    minimum_jaccard: float


@dataclass(frozen=True, slots=True)
class _PreparedText:
    product_id: uuid.UUID
    category_key: str
    normalized: str
    tokens: frozenset[str]
    simhash: int


class _ResultBuilder:
    def __init__(self, product_ids: Iterable[uuid.UUID]) -> None:
        self._codes: dict[uuid.UUID, set[DuplicateFailureCode]] = {
            item: set() for item in product_ids
        }
        self._counts: dict[uuid.UUID, dict[DuplicateFailureCode, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._peers: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)

    def add_cluster(
        self,
        product_ids: Sequence[uuid.UUID],
        code: DuplicateFailureCode,
    ) -> None:
        ordered = tuple(sorted(product_ids, key=str))
        if len(ordered) < 2:
            return
        peer_count = len(ordered) - 1
        for product_id in ordered:
            self._codes[product_id].add(code)
            self._counts[product_id][code] += peer_count
            samples = (item for item in ordered if item != product_id)
            self._add_peer_samples(product_id, samples)

    def add_pair(
        self,
        left: uuid.UUID,
        right: uuid.UUID,
        code: DuplicateFailureCode,
    ) -> None:
        if left == right:
            return
        for product_id, peer_id in ((left, right), (right, left)):
            self._codes[product_id].add(code)
            self._counts[product_id][code] += 1
            self._add_peer_samples(product_id, (peer_id,))

    def _add_peer_samples(
        self,
        product_id: uuid.UUID,
        candidates: Iterable[uuid.UUID],
    ) -> None:
        peers = self._peers[product_id]
        for candidate in candidates:
            if len(peers) >= _MAX_PEER_SAMPLES:
                return
            peers.add(candidate)

    def results(self) -> dict[uuid.UUID, DuplicateContentResult]:
        return {
            product_id: DuplicateContentResult(
                product_id=product_id,
                failure_codes=tuple(sorted(self._codes[product_id])),
                peer_samples=tuple(sorted(self._peers[product_id], key=str)),
                match_counts=dict(sorted(self._counts[product_id].items())),
            )
            for product_id in sorted(self._codes, key=str)
        }


def build_duplicate_content_index(
    records: Sequence[DuplicateContentRecord],
) -> dict[uuid.UUID, DuplicateContentResult]:
    """Build deterministic exact and conservative near-duplicate results.

    Comparisons are category-scoped. Exact groups are processed without expanding
    all peer pairs. Near candidates use four 16-bit SimHash bands; Hamming distance
    <= 3 guarantees at least one shared band, then token Jaccard verifies the pair.
    """

    ordered_records = tuple(sorted(records, key=lambda item: str(item.product_id)))
    builder = _ResultBuilder(item.product_id for item in ordered_records)
    plans = (
        _FieldPlan(
            field_name="title",
            exact_code="title_exact_duplicate",
            near_code="title_near_duplicate",
            minimum_chars=16,
            minimum_tokens=4,
            minimum_jaccard=0.75,
        ),
        _FieldPlan(
            field_name="description",
            exact_code="description_exact_duplicate",
            near_code="description_near_duplicate",
            minimum_chars=80,
            minimum_tokens=12,
            minimum_jaccard=0.85,
        ),
    )
    for plan in plans:
        prepared = _prepare_records(
            ordered_records,
            field_name=plan.field_name,
            minimum_chars=plan.minimum_chars,
            minimum_tokens=plan.minimum_tokens,
        )
        exact_signatures = _add_exact_clusters(
            prepared,
            builder=builder,
            code=plan.exact_code,
        )
        _add_near_pairs(
            prepared,
            exact_signatures=exact_signatures,
            builder=builder,
            code=plan.near_code,
            minimum_jaccard=plan.minimum_jaccard,
        )
    return builder.results()


def _prepare_records(
    records: Sequence[DuplicateContentRecord],
    *,
    field_name: str,
    minimum_chars: int,
    minimum_tokens: int,
) -> tuple[_PreparedText, ...]:
    prepared: list[_PreparedText] = []
    for record in records:
        value = record.title if field_name == "title" else record.description
        normalized = _normalize_text(value)
        tokens = frozenset(_tokens(normalized))
        if len(normalized) < minimum_chars or len(tokens) < minimum_tokens:
            continue
        prepared.append(
            _PreparedText(
                product_id=record.product_id,
                category_key=record.category_key,
                normalized=normalized,
                tokens=tokens,
                simhash=_simhash(_features(normalized)),
            )
        )
    return tuple(prepared)


def _add_exact_clusters(
    prepared: Sequence[_PreparedText],
    *,
    builder: _ResultBuilder,
    code: DuplicateFailureCode,
) -> dict[uuid.UUID, str]:
    groups: dict[tuple[str, str], list[uuid.UUID]] = defaultdict(list)
    signatures: dict[uuid.UUID, str] = {}
    for item in prepared:
        signature = hashlib.sha256(item.normalized.encode("utf-8")).hexdigest()
        signatures[item.product_id] = signature
        groups[(item.category_key, signature)].append(item.product_id)
    for product_ids in groups.values():
        builder.add_cluster(product_ids, code)
    return signatures


def _add_near_pairs(
    prepared: Sequence[_PreparedText],
    *,
    exact_signatures: Mapping[uuid.UUID, str],
    builder: _ResultBuilder,
    code: DuplicateFailureCode,
    minimum_jaccard: float,
) -> None:
    by_id = {item.product_id: item for item in prepared}
    buckets: dict[tuple[str, int, int], list[uuid.UUID]] = defaultdict(list)
    for item in prepared:
        for band_index, band_value in _simhash_bands(item.simhash):
            buckets[(item.category_key, band_index, band_value)].append(item.product_id)

    candidates: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for product_ids in buckets.values():
        ordered = sorted(set(product_ids), key=str)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                candidates.add((left, right))

    for left_id, right_id in sorted(candidates, key=lambda item: (str(item[0]), str(item[1]))):
        if exact_signatures[left_id] == exact_signatures[right_id]:
            continue
        left_text = by_id[left_id]
        right_text = by_id[right_id]
        if _hamming_distance(left_text.simhash, right_text.simhash) > _SIMHASH_MAX_DISTANCE:
            continue
        if _jaccard(left_text.tokens, right_text.tokens) < minimum_jaccard:
            continue
        builder.add_pair(left_id, right_id, code)


def _normalize_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(value))


def _features(value: str) -> tuple[str, ...]:
    tokens = _tokens(value)
    if len(tokens) >= 3:
        return tuple(" ".join(tokens[index : index + 3]) for index in range(len(tokens) - 2))
    if len(tokens) >= 2:
        return tuple(" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1))
    compact = "".join(tokens)
    if len(compact) >= 3:
        return tuple(compact[index : index + 3] for index in range(len(compact) - 2))
    return tokens


def _simhash(features: Sequence[str]) -> int:
    if not features:
        return 0
    vector = [0] * _SIMHASH_BITS
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(_SIMHASH_BITS):
            vector[bit] += 1 if value & (1 << bit) else -1
    fingerprint = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def _simhash_bands(value: int) -> tuple[tuple[int, int], ...]:
    mask = (1 << _SIMHASH_BAND_BITS) - 1
    return tuple(
        (band_index, (value >> (band_index * _SIMHASH_BAND_BITS)) & mask)
        for band_index in range(_SIMHASH_BANDS)
    )


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
