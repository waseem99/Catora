from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PILOT_ACCEPTANCE_VERSION: Literal["restaurant-pilot-acceptance/v1"] = (
    "restaurant-pilot-acceptance/v1"
)

OwnerRole = Literal[
    "business_owner",
    "backend_data_owner",
    "website_repository_owner",
    "security_privacy_owner",
    "seo_visibility_owner",
    "deployment_owner",
    "operator_acceptance_owner",
]
OwnerApprovalState = Literal["pending", "approved", "rejected"]
CapabilityState = Literal["unavailable", "discovered", "tested", "accepted", "revoked"]
ModuleState = Literal["disabled", "synthetic_tested", "accepted", "unavailable", "prohibited"]
CheckState = Literal["missing", "passed", "failed", "expired", "not_applicable"]
PlanState = Literal[
    "draft",
    "blocked",
    "ready_for_external_acceptance",
    "external_acceptance_recorded",
    "rejected",
    "rolled_back",
]
DecisionType = Literal[
    "request_external_acceptance",
    "record_external_acceptance",
    "reject",
    "record_rollback",
]

REQUIRED_OWNER_ROLES: frozenset[OwnerRole] = frozenset(
    {
        "business_owner",
        "backend_data_owner",
        "website_repository_owner",
        "security_privacy_owner",
        "seo_visibility_owner",
        "deployment_owner",
        "operator_acceptance_owner",
    }
)
REQUIRED_CHECK_KEYS = frozenset(
    {
        "production_build_live",
        "production_smoke_test",
        "safe_nonproduction_access",
        "catalog_bridge_conformance",
        "snapshot_reconciliation",
        "replay_idempotency",
        "tenant_isolation",
        "restricted_field_rejection",
        "backup_restore",
        "rollback_rehearsal",
        "disconnect_restore",
        "ordering_path_isolation",
        "deployment_isolation",
        "sanitized_report_bundle",
        "operator_acceptance",
    }
)
_REQUIRED_PROHIBITED_FIELDS = frozenset(
    {
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
    }
)
_REQUIRED_MODULES = frozenset(
    {
        "restaurant_domain",
        "restaurant_catalog_bridge",
        "restaurant_audits",
        "restaurant_answer_evaluation",
        "restaurant_operations_console",
    }
)
_REQUIRED_SYSTEMS = frozenset(
    {
        "restaurant_backend",
        "website_repository",
        "production_website",
        "deployment_platform",
    }
)


class RestaurantPilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PilotOwner(RestaurantPilotModel):
    role: OwnerRole
    owner_reference: str = Field(min_length=2, max_length=500)
    approval_state: OwnerApprovalState = "pending"
    approved_at: datetime | None = None
    approval_evidence_reference: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_approval(self) -> PilotOwner:
        if self.approval_state == "approved":
            if self.approved_at is None or self.approval_evidence_reference is None:
                raise ValueError("Approved owners require dated approval evidence")
        if self.approved_at is not None and self.approved_at.tzinfo is None:
            raise ValueError("Owner approved_at must be timezone-aware")
        return self


class PilotAccessGrant(RestaurantPilotModel):
    system_key: str = Field(pattern=r"^[a-z0-9_.:-]{3,100}$")
    capability: str = Field(min_length=3, max_length=200)
    state: CapabilityState
    credential_reference: str | None = Field(default=None, max_length=500)
    evidence_reference: str | None = Field(default=None, max_length=1_000)
    tested_at: datetime | None = None

    @model_validator(mode="after")
    def validate_access(self) -> PilotAccessGrant:
        if self.credential_reference is not None:
            if not self.credential_reference.startswith(("env:", "vault:", "secret:")):
                raise ValueError("Credentials must use a managed reference")
            lowered = self.credential_reference.casefold()
            if any(token in lowered for token in ("password=", "token=", "secret=")):
                raise ValueError("Credential references cannot contain secret values")
        if self.state in {"tested", "accepted"}:
            if self.tested_at is None or self.evidence_reference is None:
                raise ValueError("Tested or accepted access requires dated evidence")
        if self.tested_at is not None and self.tested_at.tzinfo is None:
            raise ValueError("Access tested_at must be timezone-aware")
        return self


class PilotFieldPolicy(RestaurantPilotModel):
    approved_fields: tuple[str, ...] = Field(min_length=1, max_length=500)
    prohibited_fields: tuple[str, ...] = Field(min_length=10, max_length=500)
    approved_by_reference: str = Field(min_length=2, max_length=500)
    approval_evidence_reference: str = Field(min_length=3, max_length=1_000)
    approved_at: datetime

    @model_validator(mode="after")
    def validate_policy(self) -> PilotFieldPolicy:
        if self.approved_at.tzinfo is None:
            raise ValueError("Field-policy approved_at must be timezone-aware")
        approved = {field.casefold() for field in self.approved_fields}
        prohibited = {field.casefold() for field in self.prohibited_fields}
        if approved & prohibited:
            raise ValueError("Approved and prohibited fields cannot overlap")
        if not _REQUIRED_PROHIBITED_FIELDS.issubset(prohibited):
            raise ValueError("Customer, transaction and credential fields must be prohibited")
        if any(
            token in field
            for field in approved
            for token in ("customer", "order", "payment", "session", "token", "password")
        ):
            raise ValueError("Approved fields cannot include restricted data domains")
        return self


class PilotRollbackContract(RestaurantPilotModel):
    rollback_owner_reference: str = Field(min_length=2, max_length=500)
    runbook_reference: str = Field(min_length=3, max_length=1_000)
    source_disable_method: str = Field(min_length=3, max_length=500)
    provider_revoke_method: str = Field(min_length=3, max_length=500)
    ordering_dependency: Literal[False] = False
    deployment_dependency: Literal[False] = False
    direct_database_dependency: Literal[False] = False


class RestaurantPilotPlan(RestaurantPilotModel):
    contract_version: Literal["restaurant-pilot-acceptance/v1"] = PILOT_ACCEPTANCE_VERSION
    pilot_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,99}$")
    client_reference: str = Field(min_length=2, max_length=200)
    environment: Literal["production"] = "production"
    release_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    owners: tuple[PilotOwner, ...] = Field(min_length=7, max_length=20)
    access_grants: tuple[PilotAccessGrant, ...] = Field(min_length=4, max_length=100)
    field_policy: PilotFieldPolicy
    module_states: dict[str, ModuleState] = Field(min_length=5, max_length=100)
    rollback_contract: PilotRollbackContract
    submitted_at: datetime
    direct_source_mutation_allowed: Literal[False] = False
    automatic_merge_allowed: Literal[False] = False
    automatic_deploy_allowed: Literal[False] = False
    automatic_provider_mutation_allowed: Literal[False] = False
    automatic_review_posting_allowed: Literal[False] = False
    automatic_outreach_sending_allowed: Literal[False] = False
    ordering_writeback_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_plan(self) -> RestaurantPilotPlan:
        if self.submitted_at.tzinfo is None:
            raise ValueError("Plan submitted_at must be timezone-aware")
        roles = [owner.role for owner in self.owners]
        if set(roles) != REQUIRED_OWNER_ROLES or len(roles) != len(REQUIRED_OWNER_ROLES):
            raise ValueError("Exactly one owner is required for every pilot role")
        grants = [grant.system_key for grant in self.access_grants]
        if len(grants) != len(set(grants)):
            raise ValueError("Access system keys must be unique")
        missing_systems = _REQUIRED_SYSTEMS.difference(grants)
        if missing_systems:
            raise ValueError(f"Required access systems are missing: {sorted(missing_systems)}")
        missing_modules = _REQUIRED_MODULES.difference(self.module_states)
        if missing_modules:
            raise ValueError(f"Required module states are missing: {sorted(missing_modules)}")
        return self


class PilotAcceptanceCheck(RestaurantPilotModel):
    check_key: str = Field(pattern=r"^[a-z0-9_.:-]{3,100}$")
    category: Literal[
        "production",
        "security",
        "data",
        "conformance",
        "isolation",
        "resilience",
        "reporting",
        "acceptance",
    ]
    state: CheckState
    evidence_reference: str | None = Field(default=None, max_length=1_000)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    reviewer_role: OwnerRole | None = None
    reviewer_reference: str | None = Field(default=None, max_length=500)
    details: dict[str, str | int | bool] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def validate_check(self) -> PilotAcceptanceCheck:
        if self.state == "passed":
            required = (
                self.evidence_reference,
                self.evidence_sha256,
                self.observed_at,
                self.reviewer_role,
                self.reviewer_reference,
            )
            if any(value is None for value in required):
                raise ValueError("Passed checks require evidence, timestamp and reviewer")
        for value in (self.observed_at, self.expires_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Check timestamps must be timezone-aware")
        if (
            self.observed_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.observed_at
        ):
            raise ValueError("Check expires_at must be later than observed_at")
        return self


class PilotReadiness(RestaurantPilotModel):
    state: Literal["blocked", "ready_for_external_acceptance", "external_acceptance_recorded"]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    passed_checks: tuple[str, ...]
    unavailable_capabilities: tuple[str, ...]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    readiness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    external_authorization_required: Literal[True] = True
    live_activation_allowed: Literal[False] = False
    live_activation_performed: Literal[False] = False


class PilotAcceptanceDecision(RestaurantPilotModel):
    decision: DecisionType
    repository_readiness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_authorization_reference: str | None = Field(default=None, max_length=1_000)
    external_authorization_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    decision_note: str = Field(min_length=3, max_length=2_000)
    decided_at: datetime
    live_activation_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision(self) -> PilotAcceptanceDecision:
        if self.decided_at.tzinfo is None:
            raise ValueError("Decision decided_at must be timezone-aware")
        if self.decision == "record_external_acceptance":
            if not self.external_authorization_reference or not self.external_authorization_sha256:
                raise ValueError("External acceptance requires a hashed authorization reference")
        return self


class PilotDisconnectRun(RestaurantPilotModel):
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,200}$")
    state: Literal["passed", "failed"]
    started_at: datetime
    completed_at: datetime
    evidence_reference: str = Field(min_length=3, max_length=1_000)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordering_impact_observed: Literal[False] = False
    deployment_impact_observed: Literal[False] = False
    source_access_revoked: bool
    provider_access_revoked: bool
    summary: dict[str, str | int | bool] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def validate_disconnect(self) -> PilotDisconnectRun:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("Disconnect timestamps must be timezone-aware")
        if self.completed_at <= self.started_at:
            raise ValueError("Disconnect completed_at must be later than started_at")
        if self.state == "passed" and not self.source_access_revoked:
            raise ValueError("A passed disconnect must revoke source access")
        return self
