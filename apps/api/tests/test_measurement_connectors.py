from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from catora_api.measurement import (
    MeasurementCapabilityUnavailable,
    MeasurementComparison,
    MeasurementObservation,
    MeasurementProviderCapability,
    MeasurementService,
    MeasurementServiceError,
    compare_measurement_windows,
    dimension_hash,
    reconcile_measurement_batch,
    unavailable_provider,
    validate_external_ai_observation,
)

START = datetime(2026, 7, 1, tzinfo=UTC)


def _observation(**overrides: object) -> MeasurementObservation:
    values: dict[str, object] = {
        "provider": "google_search_console",
        "external_property_id": "sc-domain:example.test",
        "metric_key": "clicks",
        "metric_version": "gsc/v1",
        "value_microunits": 1_000_000,
        "dimensions": {
            "page": "https://example.test/locations/lahore",
            "device": "mobile",
        },
        "window_start": START,
        "window_end": START + timedelta(days=7),
        "timezone": "Asia/Karachi",
        "sample_state": "complete",
        "freshness_state": "current",
        "source_definition": {"unit": "count", "aggregate": True},
        "observed_at": START + timedelta(days=8),
        "observation_hash": hashlib.sha256(b"measurement").hexdigest(),
    }
    values.update(overrides)
    return MeasurementObservation(**values)  # type: ignore[arg-type]


def test_forbidden_user_and_transaction_dimensions_fail_closed() -> None:
    for key in (
        "user_id",
        "client_id",
        "session_id",
        "email",
        "order_id",
        "transaction_id",
    ):
        with pytest.raises(ValidationError, match="identifiers"):
            _observation(dimensions={key: "secret-value"})


def test_unknown_dimensions_do_not_enter_aggregate_store() -> None:
    with pytest.raises(ValidationError, match="allowlist"):
        _observation(dimensions={"campaign_secret": "value"})


def test_dimension_hash_is_order_independent() -> None:
    assert dimension_hash({"page": "/a", "device": "mobile"}) == dimension_hash(
        {"device": "mobile", "page": "/a"}
    )


def test_measurement_comparison_reconciles_delta_without_causal_claim() -> None:
    baseline = _observation()
    selected = _observation(
        value_microunits=1_500_000,
        window_start=START + timedelta(days=7),
        window_end=START + timedelta(days=14),
        observation_hash=hashlib.sha256(b"selected").hexdigest(),
    )
    comparison = compare_measurement_windows(baseline, selected)
    assert comparison.delta_microunits == 500_000
    assert comparison.interpretation == "correlation_only"
    assert comparison.causal_claim_allowed is False
    with pytest.raises(ValidationError, match="cannot claim causality"):
        MeasurementComparison(
            **comparison.model_dump(exclude={"causal_claim_allowed"}),
            causal_claim_allowed=True,
        )


def test_partial_or_sampled_windows_do_not_present_complete_comparison() -> None:
    comparison = compare_measurement_windows(
        _observation(sample_state="sampled"),
        _observation(
            sample_state="complete",
            window_start=START + timedelta(days=7),
            window_end=START + timedelta(days=14),
            observation_hash=hashlib.sha256(b"second").hexdigest(),
        ),
    )
    assert comparison.sample_state == "partial"


def test_external_ai_observation_requires_explicit_provider_metadata() -> None:
    observation = _observation(
        provider="external_ai_search",
        metric_key="citation_observed",
        metric_version="external-ai/v1",
        dimensions={
            "provider_model": "example-model",
            "locale": "en-PK",
            "market": "PK",
        },
    )
    validate_external_ai_observation(observation)
    with pytest.raises(ValueError, match="lacks"):
        validate_external_ai_observation(
            observation.model_copy(update={"dimensions": {"locale": "en-PK"}})
        )


def test_batch_reconciliation_distinguishes_duplicate_and_freshness() -> None:
    first = _observation()
    duplicate = first.model_copy()
    stale = _observation(
        freshness_state="stale",
        observation_hash=hashlib.sha256(b"stale").hexdigest(),
    )
    assert reconcile_measurement_batch((first, duplicate, stale)) == {
        "received": 3,
        "unique": 2,
        "duplicate": 1,
        "current": 2,
        "stale": 1,
        "disconnected": 0,
        "unavailable": 0,
    }


def test_account_contract_rejects_raw_credentials_and_unaccepted_live_access() -> None:
    service = MeasurementService()
    capabilities = (
        MeasurementProviderCapability(
            operation="properties.read",
            state="documented",
        ),
    )
    with pytest.raises(MeasurementServiceError, match="credential references"):
        service._validate_account_contract(  # noqa: SLF001
            provider="google_search_console",
            credential_reference="raw-token",
            capabilities=capabilities,
            live_acceptance_confirmed=False,
        )
    with pytest.raises(MeasurementServiceError, match="successful account-level acceptance"):
        service._validate_account_contract(  # noqa: SLF001
            provider="google_search_console",
            credential_reference="env:CATORA_GSC_TOKEN",
            capabilities=(
                MeasurementProviderCapability(
                    operation="properties.read",
                    state="tested",
                    tested_at=START,
                ),
            ),
            live_acceptance_confirmed=False,
        )


@pytest.mark.asyncio
async def test_real_provider_is_explicitly_unavailable() -> None:
    provider = unavailable_provider("ga4")
    with pytest.raises(MeasurementCapabilityUnavailable):
        await provider.discover_properties()


def test_measurement_tables_register_additively() -> None:
    from catora_api.db import Base

    assert {
        "measurement_provider_accounts",
        "measurement_properties",
        "measurement_observations",
        "measurement_attribution_links",
        "measurement_change_annotations",
    }.issubset(Base.metadata.tables)
