from __future__ import annotations

import hashlib
import json
from collections import Counter

from catora_api.measurement.models import (
    MeasurementComparison,
    MeasurementObservation,
    SampleState,
)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def dimension_hash(dimensions: dict[str, str]) -> str:
    return canonical_hash(dict(sorted(dimensions.items())))


def compare_measurement_windows(
    baseline: MeasurementObservation,
    selected: MeasurementObservation,
) -> MeasurementComparison:
    if baseline.metric_key != selected.metric_key:
        raise ValueError("Measurement comparison requires the same metric")
    if baseline.metric_version != selected.metric_version:
        raise ValueError("Measurement metric definitions differ")
    if baseline.provider != selected.provider:
        raise ValueError("Measurement providers differ")
    if baseline.external_property_id != selected.external_property_id:
        raise ValueError("Measurement properties differ")
    if baseline.dimensions != selected.dimensions:
        raise ValueError("Measurement dimensions differ")
    if baseline.timezone != selected.timezone:
        raise ValueError("Measurement timezones differ")
    sample_state: SampleState = (
        "complete"
        if baseline.sample_state == selected.sample_state == "complete"
        else "partial"
    )
    return MeasurementComparison(
        metric_key=baseline.metric_key,
        baseline_value_microunits=baseline.value_microunits,
        selected_value_microunits=selected.value_microunits,
        delta_microunits=(
            selected.value_microunits - baseline.value_microunits
        ),
        baseline_window_start=baseline.window_start,
        baseline_window_end=baseline.window_end,
        selected_window_start=selected.window_start,
        selected_window_end=selected.window_end,
        sample_state=sample_state,
    )


def reconcile_measurement_batch(
    observations: tuple[MeasurementObservation, ...],
) -> dict[str, int]:
    hashes = {observation.observation_hash for observation in observations}
    counts = Counter(observation.freshness_state for observation in observations)
    return {
        "received": len(observations),
        "unique": len(hashes),
        "duplicate": len(observations) - len(hashes),
        "current": counts["current"],
        "stale": counts["stale"],
        "disconnected": counts["disconnected"],
        "unavailable": counts["unavailable"],
    }


def validate_external_ai_observation(
    observation: MeasurementObservation,
) -> None:
    if observation.provider != "external_ai_search":
        raise ValueError("Observation is not an external AI/search sample")
    required = {"provider_model", "locale", "market"}
    if not required.issubset(observation.dimensions):
        raise ValueError(
            "External AI/search observation lacks provider/model/locale/market"
        )
    if observation.metric_key not in {
        "citation_observed",
        "referral_sessions",
        "factual_accuracy_basis_points",
    }:
        raise ValueError("External AI/search metric is unsupported")
