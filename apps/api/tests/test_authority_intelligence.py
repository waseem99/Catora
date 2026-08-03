from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from catora_api.authority import (
    AuthorityCapability,
    AuthorityCapabilityUnavailable,
    AuthorityObservation,
    AuthorityService,
    AuthorityServiceError,
    OutreachDraft,
    derive_opportunity,
    observation_risk,
    reconcile_authority_batch,
    unavailable_provider,
)

OBSERVED_AT = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
BRAND_ID = uuid.uuid4()


def _observation(**overrides: object) -> AuthorityObservation:
    values: dict[str, object] = {
        "provider": "synthetic",
        "external_account_id": "synthetic-authority",
        "external_observation_id": "observation-1",
        "observation_type": "backlink",
        "brand_id": BRAND_ID,
        "source_url": "https://publisher.example.test/restaurants/north-grill",
        "target_url": "https://restaurant.example.test/locations/lahore",
        "source_title": "Lahore restaurant guide",
        "anchor_or_mention_text": "North Grill Lahore",
        "provider_metrics": {"source_quality_basis_points": 7500},
        "identity_state": "exact",
        "identity_method": "approved_brand_and_url",
        "link_state": "lost",
        "nofollow": False,
        "sponsored": False,
        "observed_at": OBSERVED_AT,
        "source_updated_at": OBSERVED_AT,
        "observation_hash": hashlib.sha256(b"authority-observation").hexdigest(),
    }
    values.update(overrides)
    return AuthorityObservation(**values)  # type: ignore[arg-type]


def test_provider_metrics_reject_user_and_transaction_identifiers() -> None:
    for key in (
        "user_id",
        "customer_id",
        "order_id",
        "transaction_id",
        "email",
        "phone",
        "ip",
        "session_id",
    ):
        with pytest.raises(ValidationError, match="prohibited identifiers"):
            _observation(provider_metrics={key: "not-allowed"})


def test_paid_link_and_guarantee_schemes_are_prohibited() -> None:
    for text in (
        "Buy backlinks with guaranteed ranking",
        "Paid link placement package",
        "Private blog network PBN opportunity",
    ):
        observation = _observation(
            source_title=text,
            observation_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        assert observation_risk(observation) == "prohibited"
        assert derive_opportunity(observation) is None


def test_ambiguous_identity_is_suppressed_and_never_actionable() -> None:
    observation = _observation(
        brand_id=None,
        identity_state="ambiguous",
        identity_method="multiple_name_matches",
    )
    opportunity = derive_opportunity(observation)
    assert opportunity is not None
    assert opportunity.state == "suppressed"
    assert opportunity.risk_state == "review_required"
    assert opportunity.score_basis_points == 0


def test_lost_link_creates_reclamation_with_evidence_and_verification() -> None:
    observation = _observation()
    opportunity = derive_opportunity(observation)
    assert opportunity is not None
    assert opportunity.opportunity_type == "link_reclamation"
    assert opportunity.evidence_hashes == (observation.observation_hash,)
    assert opportunity.verification_method
    assert opportunity.score_basis_points == 7_500


def test_outreach_contract_cannot_enable_sending() -> None:
    opportunity_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        OutreachDraft(
            opportunity_id=opportunity_id,
            channel="email",
            subject="Manual relationship follow-up",
            body="A factual, manually reviewed draft.",
            factual_claims=("The source currently mentions the restaurant.",),
            evidence_hashes=(hashlib.sha256(b"evidence").hexdigest(),),
            suppression_checked=True,
            legal_basis_confirmed=True,
            send_allowed=True,
        )
    with pytest.raises(ValidationError, match="suppression checking"):
        OutreachDraft(
            opportunity_id=opportunity_id,
            channel="email",
            subject="Manual relationship follow-up",
            body="A factual, manually reviewed draft.",
            factual_claims=(),
            evidence_hashes=(hashlib.sha256(b"evidence").hexdigest(),),
            suppression_checked=False,
            legal_basis_confirmed=True,
        )


def test_batch_reconciliation_separates_duplicates_and_prohibited_records() -> None:
    valid = _observation()
    prohibited = _observation(
        external_observation_id="observation-2",
        source_title="Buy backlinks now",
        observation_hash=hashlib.sha256(b"prohibited").hexdigest(),
    )
    summary = reconcile_authority_batch((valid, valid.model_copy(), prohibited))
    assert summary == {
        "received": 3,
        "unique": 2,
        "duplicate": 1,
        "matched": 2,
        "ambiguous": 0,
        "unmatched": 0,
        "prohibited": 1,
        "opportunities": 1,
    }


def test_account_contract_rejects_raw_credentials_and_unaccepted_live_access() -> None:
    service = AuthorityService()
    documented = (
        AuthorityCapability(
            operation="observations.read",
            state="documented",
            scope="provider documentation only",
        ),
    )
    with pytest.raises(AuthorityServiceError, match="credential references"):
        service._validate_account_contract(
            provider="backlink_provider",
            credential_reference="raw-token",
            capabilities=documented,
        )
    with pytest.raises(AuthorityServiceError, match="cannot be granted or tested"):
        service._validate_account_contract(
            provider="backlink_provider",
            credential_reference="env:CATORA_BACKLINK_TOKEN",
            capabilities=(
                AuthorityCapability(
                    operation="observations.read",
                    state="tested",
                    scope="unaccepted live account",
                    tested_at=OBSERVED_AT,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_real_authority_provider_is_explicitly_unavailable() -> None:
    provider = unavailable_provider("mention_provider")
    with pytest.raises(AuthorityCapabilityUnavailable):
        async for _ in provider.observations():
            pass


def test_authority_tables_register_additively() -> None:
    from catora_api.db import Base

    assert {
        "authority_provider_accounts",
        "authority_observations",
        "authority_opportunities",
        "authority_suppressions",
        "authority_outreach_drafts",
        "authority_outreach_decisions",
    }.issubset(Base.metadata.tables)
