from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from catora_api.restaurant_pilot.models import (
    REQUIRED_CHECK_KEYS,
    PilotAcceptanceCheck,
    PilotReadiness,
    RestaurantPilotPlan,
)

_REQUIRED_ACCEPTED_SYSTEMS = frozenset(
    {
        "restaurant_backend",
        "website_repository",
        "production_website",
        "deployment_platform",
    }
)
_REQUIRED_READY_MODULES = frozenset(
    {
        "restaurant_domain",
        "restaurant_catalog_bridge",
        "restaurant_audits",
        "restaurant_answer_evaluation",
        "restaurant_operations_console",
    }
)
_OPTIONAL_MODULES = frozenset(
    {
        "governed_git_publishing",
        "local_profile_intelligence",
        "reputation_intelligence",
        "measurement_connectors",
        "authority_intelligence",
        "restaurant_monitoring",
    }
)
_RECONCILIATION_KEYS = frozenset(
    {
        "source_count",
        "accepted_count",
        "normalized_count",
        "excluded_count",
        "rejected_count",
    }
)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def plan_hash(plan: RestaurantPilotPlan) -> str:
    return canonical_hash(plan.model_dump(mode="json", exclude_none=True))


def evaluate_pilot_readiness(
    plan: RestaurantPilotPlan,
    checks: tuple[PilotAcceptanceCheck, ...],
    *,
    external_acceptance_recorded: bool = False,
    evaluated_at: datetime | None = None,
) -> PilotReadiness:
    instant = evaluated_at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")

    blockers: list[str] = []
    warnings: list[str] = []

    pending_owners = sorted(
        owner.role
        for owner in plan.owners
        if owner.approval_state != "approved"
    )
    if pending_owners:
        blockers.append("Unapproved owners: " + ", ".join(pending_owners))

    access_by_system = {grant.system_key: grant for grant in plan.access_grants}
    for system in sorted(_REQUIRED_ACCEPTED_SYSTEMS):
        grant = access_by_system.get(system)
        if grant is None:
            blockers.append(f"Missing required access grant: {system}")
        elif grant.state != "accepted":
            blockers.append(f"Required access is not accepted: {system}")

    for module in sorted(_REQUIRED_READY_MODULES):
        state = plan.module_states.get(module)
        if state not in {"synthetic_tested", "accepted"}:
            blockers.append(f"Required module is not ready: {module}")
    for module in sorted(_OPTIONAL_MODULES):
        state = plan.module_states.get(module)
        if state is None or state in {"disabled", "unavailable", "prohibited"}:
            warnings.append(f"Optional module is not accepted: {module}")

    check_by_key: dict[str, PilotAcceptanceCheck] = {}
    duplicate_keys: set[str] = set()
    for check in checks:
        if check.check_key in check_by_key:
            duplicate_keys.add(check.check_key)
        check_by_key[check.check_key] = check
    if duplicate_keys:
        blockers.append("Duplicate acceptance checks: " + ", ".join(sorted(duplicate_keys)))

    missing_checks = sorted(REQUIRED_CHECK_KEYS.difference(check_by_key))
    if missing_checks:
        blockers.append("Missing acceptance checks: " + ", ".join(missing_checks))

    passed_checks: list[str] = []
    for key in sorted(REQUIRED_CHECK_KEYS.intersection(check_by_key)):
        check = check_by_key[key]
        if check.state != "passed":
            blockers.append(f"Acceptance check has not passed: {key}")
            continue
        if check.expires_at is not None and check.expires_at <= instant:
            blockers.append(f"Acceptance check is expired: {key}")
            continue
        if key == "snapshot_reconciliation":
            try:
                validate_reconciliation_details(check)
            except ValueError as exc:
                blockers.append(f"Snapshot reconciliation is invalid: {exc}")
                continue
        if (
            key in {"ordering_path_isolation", "deployment_isolation"}
            and check.details.get("impact_observed") is not False
        ):
            blockers.append(f"Isolation check observed an impact: {key}")
            continue
        if (
            key == "restricted_field_rejection"
            and check.details.get("restricted_fields_accepted") is not False
        ):
            blockers.append("Restricted-field rejection did not fail closed")
            continue
        passed_checks.append(key)

    unavailable_capabilities = tuple(
        sorted(
            f"{grant.system_key}:{grant.capability}"
            for grant in plan.access_grants
            if grant.state in {"unavailable", "revoked"}
        )
    )

    state = "blocked"
    if not blockers:
        state = (
            "external_acceptance_recorded"
            if external_acceptance_recorded
            else "ready_for_external_acceptance"
        )
    readiness_payload = {
        "plan_sha256": plan_hash(plan),
        "state": state,
        "blockers": sorted(blockers),
        "warnings": sorted(warnings),
        "passed_checks": passed_checks,
        "unavailable_capabilities": unavailable_capabilities,
        "evaluated_at": instant.isoformat(),
        "external_authorization_required": True,
        "live_activation_allowed": False,
        "live_activation_performed": False,
    }
    return PilotReadiness(
        state=state,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        passed_checks=tuple(passed_checks),
        unavailable_capabilities=unavailable_capabilities,
        plan_sha256=plan_hash(plan),
        readiness_sha256=canonical_hash(readiness_payload),
        evaluated_at=instant,
    )


def validate_reconciliation_details(check: PilotAcceptanceCheck) -> None:
    if check.check_key != "snapshot_reconciliation":
        raise ValueError("Check is not snapshot_reconciliation")
    missing = _RECONCILIATION_KEYS.difference(check.details)
    if missing:
        raise ValueError("Missing reconciliation fields: " + ", ".join(sorted(missing)))
    values: dict[str, int] = {}
    for key in _RECONCILIATION_KEYS:
        value = check.details[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        values[key] = value
    if values["source_count"] != (
        values["accepted_count"]
        + values["excluded_count"]
        + values["rejected_count"]
    ):
        raise ValueError("Source count does not reconcile")
    if values["normalized_count"] != values["accepted_count"]:
        raise ValueError("Normalized count must equal accepted count")
