from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from catora_api.restaurant_pilot import (
    REQUIRED_CHECK_KEYS,
    PilotAcceptanceCheck,
    PilotAcceptanceDecision,
    PilotAccessGrant,
    PilotDisconnectRun,
    PilotFieldPolicy,
    PilotOwner,
    PilotRollbackContract,
    RestaurantPilotPlan,
    evaluate_pilot_readiness,
    validate_reconciliation_details,
)

NOW = datetime(2026, 8, 3, 7, 0, tzinfo=UTC)
HASH = hashlib.sha256(b"evidence").hexdigest()


def _owners(*, pending_role: str | None = None) -> tuple[PilotOwner, ...]:
    roles = (
        "business_owner",
        "backend_data_owner",
        "website_repository_owner",
        "security_privacy_owner",
        "seo_visibility_owner",
        "deployment_owner",
        "operator_acceptance_owner",
    )
    return tuple(
        PilotOwner(
            role=role,  # type: ignore[arg-type]
            owner_reference=f"directory:{role}",
            approval_state="pending" if role == pending_role else "approved",
            approved_at=None if role == pending_role else NOW,
            approval_evidence_reference=(
                None if role == pending_role else f"evidence:owner:{role}:{HASH}"
            ),
        )
        for role in roles
    )


def _access() -> tuple[PilotAccessGrant, ...]:
    return tuple(
        PilotAccessGrant(
            system_key=system,
            capability="read-only acceptance fixture",
            state="accepted",
            credential_reference=f"vault:restaurant-pilot/{system}",
            evidence_reference=f"evidence:access:{system}:{HASH}",
            tested_at=NOW,
        )
        for system in (
            "restaurant_backend",
            "website_repository",
            "production_website",
            "deployment_platform",
        )
    )


def _plan(*, pending_role: str | None = None) -> RestaurantPilotPlan:
    return RestaurantPilotPlan(
        pilot_key="ranchers-production",
        client_reference="Ranchers",
        release_revision="a" * 40,
        owners=_owners(pending_role=pending_role),
        access_grants=_access(),
        field_policy=PilotFieldPolicy(
            approved_fields=(
                "brands",
                "locations",
                "menus",
                "menu_items",
                "modifiers",
                "offers",
            ),
            prohibited_fields=(
                "customers",
                "orders",
                "payments",
                "refunds",
                "loyalty",
                "passwords",
                "sessions",
                "tokens",
                "api_keys",
                "payment_methods",
            ),
            approved_by_reference="directory:backend_data_owner",
            approval_evidence_reference=f"evidence:field-policy:{HASH}",
            approved_at=NOW,
        ),
        module_states={
            "restaurant_domain": "accepted",
            "restaurant_catalog_bridge": "synthetic_tested",
            "restaurant_audits": "accepted",
            "restaurant_answer_evaluation": "accepted",
            "restaurant_operations_console": "accepted",
            "governed_git_publishing": "accepted",
            "local_profile_intelligence": "unavailable",
            "reputation_intelligence": "unavailable",
            "measurement_connectors": "unavailable",
            "authority_intelligence": "unavailable",
            "restaurant_monitoring": "disabled",
        },
        rollback_contract=PilotRollbackContract(
            rollback_owner_reference="directory:deployment_owner",
            runbook_reference="docs:restaurant-pilot-acceptance#rollback",
            source_disable_method=(
                "Disable the approved source adapter and revoke its managed secret."
            ),
            provider_revoke_method="Revoke every accepted provider account independently.",
        ),
        submitted_at=NOW,
    )


def _checks() -> tuple[PilotAcceptanceCheck, ...]:
    checks: list[PilotAcceptanceCheck] = []
    for key in sorted(REQUIRED_CHECK_KEYS):
        details: dict[str, str | int | bool] = {}
        if key == "snapshot_reconciliation":
            details = {
                "source_count": 12,
                "accepted_count": 9,
                "normalized_count": 9,
                "excluded_count": 2,
                "rejected_count": 1,
            }
        elif key in {"ordering_path_isolation", "deployment_isolation"}:
            details = {"impact_observed": False}
        elif key == "restricted_field_rejection":
            details = {"restricted_fields_accepted": False}
        checks.append(
            PilotAcceptanceCheck(
                check_key=key,
                category="acceptance",
                state="passed",
                evidence_reference=f"evidence:check:{key}:{HASH}",
                evidence_sha256=HASH,
                observed_at=NOW,
                expires_at=NOW + timedelta(days=30),
                reviewer_role="operator_acceptance_owner",
                reviewer_reference="directory:operator_acceptance_owner",
                details=details,
            )
        )
    return tuple(checks)


def test_complete_repository_gate_is_ready_but_never_activates() -> None:
    readiness = evaluate_pilot_readiness(_plan(), _checks(), evaluated_at=NOW)
    assert readiness.state == "ready_for_external_acceptance"
    assert readiness.blockers == ()
    assert len(readiness.passed_checks) == len(REQUIRED_CHECK_KEYS)
    assert readiness.external_authorization_required is True
    assert readiness.live_activation_allowed is False
    assert readiness.live_activation_performed is False

    recorded = evaluate_pilot_readiness(
        _plan(),
        _checks(),
        external_acceptance_recorded=True,
        evaluated_at=NOW,
    )
    assert recorded.state == "external_acceptance_recorded"
    assert recorded.live_activation_allowed is False
    assert recorded.live_activation_performed is False


def test_unapproved_owner_and_missing_checks_block_readiness() -> None:
    readiness = evaluate_pilot_readiness(
        _plan(pending_role="business_owner"),
        _checks()[:-1],
        evaluated_at=NOW,
    )
    assert readiness.state == "blocked"
    assert any("Unapproved owners" in blocker for blocker in readiness.blockers)
    assert any("Missing acceptance checks" in blocker for blocker in readiness.blockers)


def test_expired_or_impacting_evidence_blocks_readiness() -> None:
    checks = list(_checks())
    index = next(
        i
        for i, check in enumerate(checks)
        if check.check_key == "ordering_path_isolation"
    )
    checks[index] = checks[index].model_copy(update={"details": {"impact_observed": True}})
    expired_index = next(
        i for i, check in enumerate(checks) if check.check_key == "backup_restore"
    )
    checks[expired_index] = checks[expired_index].model_copy(
        update={"expires_at": NOW - timedelta(seconds=1)}
    )
    readiness = evaluate_pilot_readiness(_plan(), tuple(checks), evaluated_at=NOW)
    assert readiness.state == "blocked"
    assert any("observed an impact" in blocker for blocker in readiness.blockers)
    assert any("expired" in blocker for blocker in readiness.blockers)


def test_field_policy_rejects_customer_transaction_and_credential_fields() -> None:
    with pytest.raises(ValidationError, match="cannot include restricted"):
        PilotFieldPolicy(
            approved_fields=("brands", "customer_email"),
            prohibited_fields=(
                "customers",
                "orders",
                "payments",
                "refunds",
                "loyalty",
                "passwords",
                "sessions",
                "tokens",
                "api_keys",
                "payment_methods",
            ),
            approved_by_reference="directory:data-owner",
            approval_evidence_reference=f"evidence:policy:{HASH}",
            approved_at=NOW,
        )


def test_access_grants_require_managed_references_without_values() -> None:
    with pytest.raises(ValidationError, match="managed reference"):
        PilotAccessGrant(
            system_key="restaurant_backend",
            capability="read",
            state="accepted",
            credential_reference="plaintext-token",
            evidence_reference="evidence:access",
            tested_at=NOW,
        )
    with pytest.raises(ValidationError, match="secret values"):
        PilotAccessGrant(
            system_key="restaurant_backend",
            capability="read",
            state="accepted",
            credential_reference="vault:token=secret-value",
            evidence_reference="evidence:access",
            tested_at=NOW,
        )


def test_reconciliation_requires_exact_source_accounting() -> None:
    valid = next(check for check in _checks() if check.check_key == "snapshot_reconciliation")
    validate_reconciliation_details(valid)
    invalid = valid.model_copy(
        update={
            "details": {
                "source_count": 12,
                "accepted_count": 9,
                "normalized_count": 8,
                "excluded_count": 2,
                "rejected_count": 1,
            }
        }
    )
    with pytest.raises(ValueError, match="Normalized count"):
        validate_reconciliation_details(invalid)


def test_external_acceptance_decision_requires_hashed_authorization() -> None:
    with pytest.raises(ValidationError, match="hashed authorization"):
        PilotAcceptanceDecision(
            decision="record_external_acceptance",
            repository_readiness_sha256=HASH,
            decision_note="External operator approval was reviewed.",
            decided_at=NOW,
        )
    decision = PilotAcceptanceDecision(
        decision="record_external_acceptance",
        repository_readiness_sha256=HASH,
        external_authorization_reference="evidence:external-authorization",
        external_authorization_sha256=HASH,
        decision_note="External operator approval was reviewed.",
        decided_at=NOW,
    )
    assert decision.live_activation_performed is False


def test_disconnect_contract_proves_no_ordering_or_deployment_impact() -> None:
    run = PilotDisconnectRun(
        idempotency_key="disconnect:ranchers:2026-08-03",
        state="passed",
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=5),
        evidence_reference="evidence:disconnect",
        evidence_sha256=HASH,
        source_access_revoked=True,
        provider_access_revoked=True,
    )
    assert run.ordering_impact_observed is False
    assert run.deployment_impact_observed is False
    with pytest.raises(ValidationError, match="revoke source access"):
        run.model_copy(update={"source_access_revoked": False}).__class__(
            **run.model_dump(exclude={"source_access_revoked"}),
            source_access_revoked=False,
        )


def test_pilot_tables_register_additively() -> None:
    from catora_api.db.base import Base
    from catora_api.db.models.restaurant_pilot import (  # noqa: F401
        RestaurantPilotAcceptanceCheckRecord,
        RestaurantPilotAcceptanceDecisionRecord,
        RestaurantPilotAcceptancePlanRecord,
        RestaurantPilotDisconnectRunRecord,
    )

    assert {
        "restaurant_pilot_acceptance_plans",
        "restaurant_pilot_acceptance_checks",
        "restaurant_pilot_acceptance_decisions",
        "restaurant_pilot_disconnect_runs",
    }.issubset(Base.metadata.tables)
