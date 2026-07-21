from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import cast

from catora_api.auditing.scoring import ScoreContribution
from catora_api.auditing.types import ScoreDimension

_SCORE_FORMULA_VERSION = "weighted-health-v1"
_VALID_DIMENSIONS = frozenset(
    {
        "completeness",
        "consistency",
        "variant_quality",
        "market_consistency",
        "discoverability_readiness",
    }
)
_VALID_OUTCOMES = frozenset({"passed", "failed", "not_evaluated"})


class IncrementalStateError(ValueError):
    pass


def score_contributions_from_summary(
    summary: Mapping[str, object],
) -> tuple[ScoreContribution, ...]:
    if summary.get("formula_version") != _SCORE_FORMULA_VERSION:
        raise IncrementalStateError(
            "Previous score summary uses an unsupported formula version"
        )
    overall = summary.get("overall")
    if not isinstance(overall, Mapping):
        raise IncrementalStateError("Previous score summary has no overall score payload")
    raw_contributions = overall.get("contributions")
    if not isinstance(raw_contributions, Sequence) or isinstance(
        raw_contributions, str | bytes | bytearray
    ):
        raise IncrementalStateError("Previous score summary has no contribution list")
    contributions = tuple(_parse_contribution(item) for item in raw_contributions)
    return tuple(
        sorted(
            contributions,
            key=lambda item: (
                item.product_id,
                item.variant_id or "",
                item.rule_key,
                item.check_key,
            ),
        )
    )


def merge_score_contributions(
    previous: Sequence[ScoreContribution],
    *,
    target_product_ids: set[str],
    current: Sequence[ScoreContribution],
) -> tuple[ScoreContribution, ...]:
    retained = [
        item for item in previous if item.product_id not in target_product_ids
    ]
    retained.extend(current)
    return tuple(
        sorted(
            retained,
            key=lambda item: (
                item.product_id,
                item.variant_id or "",
                item.rule_key,
                item.check_key,
            ),
        )
    )


def merge_product_snapshot_hashes(
    previous: Mapping[str, str],
    *,
    target_product_ids: set[str],
    current: Mapping[str, str],
) -> dict[str, str]:
    merged = {
        product_id: digest
        for product_id, digest in previous.items()
        if product_id not in target_product_ids
    }
    merged.update(current)
    return dict(sorted(merged.items()))


def catalog_snapshot_hash(product_hashes: Mapping[str, str]) -> str:
    payload = json.dumps(
        dict(sorted(product_hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_contribution(value: object) -> ScoreContribution:
    if not isinstance(value, Mapping):
        raise IncrementalStateError("Score contribution must be an object")
    dimension = _required_str(value, "dimension")
    if dimension not in _VALID_DIMENSIONS:
        raise IncrementalStateError(f"Unsupported score dimension {dimension!r}")
    outcome = _required_str(value, "outcome")
    if outcome not in _VALID_OUTCOMES:
        raise IncrementalStateError(f"Unsupported score outcome {outcome!r}")
    weight = _required_int(value, "weight")
    coverage = _required_int(value, "coverage_basis_points")
    if weight < 0:
        raise IncrementalStateError("Score contribution weight cannot be negative")
    if not 0 <= coverage <= 10000:
        raise IncrementalStateError(
            "Score contribution coverage_basis_points must be between 0 and 10000"
        )
    variant_id = value.get("variant_id")
    if variant_id is not None and not isinstance(variant_id, str):
        raise IncrementalStateError("Score contribution variant_id must be a string or null")
    return ScoreContribution(
        rule_key=_required_str(value, "rule_key"),
        rule_version_id=_required_str(value, "rule_version_id"),
        product_id=_required_str(value, "product_id"),
        variant_id=variant_id,
        check_key=_required_str(value, "check_key"),
        dimension=cast(ScoreDimension, dimension),
        weight=weight,
        outcome=outcome,
        coverage_basis_points=coverage,
    )


def _required_str(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise IncrementalStateError(f"Score contribution {key} must be a non-empty string")
    return item


def _required_int(value: Mapping[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise IncrementalStateError(f"Score contribution {key} must be an integer")
    return item
