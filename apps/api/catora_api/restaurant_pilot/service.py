from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.restaurant_pilot import (
    RestaurantPilotAcceptanceCheckRecord,
    RestaurantPilotAcceptanceDecisionRecord,
    RestaurantPilotAcceptancePlanRecord,
    RestaurantPilotDisconnectRunRecord,
)
from catora_api.restaurant_pilot.evaluator import (
    evaluate_pilot_readiness,
    plan_hash,
)
from catora_api.restaurant_pilot.models import (
    PilotAcceptanceCheck,
    PilotAcceptanceDecision,
    PilotDisconnectRun,
    PilotReadiness,
    RestaurantPilotPlan,
)


class RestaurantPilotServiceError(ValueError):
    pass


class RestaurantPilotService:
    async def upsert_plan(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan: RestaurantPilotPlan,
    ) -> RestaurantPilotAcceptancePlanRecord:
        digest = plan_hash(plan)
        row = await session.scalar(
            select(RestaurantPilotAcceptancePlanRecord).where(
                RestaurantPilotAcceptancePlanRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptancePlanRecord.pilot_key == plan.pilot_key,
            )
        )
        if row is None:
            row = RestaurantPilotAcceptancePlanRecord(
                workspace_id=workspace_id,
                pilot_key=plan.pilot_key,
                client_reference=plan.client_reference,
                environment=plan.environment,
                contract_version=plan.contract_version,
                release_revision=plan.release_revision,
                plan_sha256=digest,
                owners=[item.model_dump(mode="json", exclude_none=True) for item in plan.owners],
                access_grants=[
                    item.model_dump(mode="json", exclude_none=True)
                    for item in plan.access_grants
                ],
                field_policy=plan.field_policy.model_dump(mode="json"),
                module_states=dict(plan.module_states),
                rollback_contract=plan.rollback_contract.model_dump(mode="json"),
                state="draft",
                created_by_user_id=actor_user_id,
                submitted_at=plan.submitted_at,
                updated_by_user_id=actor_user_id,
                updated_at=datetime.now(UTC),
            )
            session.add(row)
            await session.flush()
            event_type = "restaurant_pilot.plan_created"
        else:
            if row.state in {"external_acceptance_recorded", "rolled_back"}:
                raise RestaurantPilotServiceError(
                    "Accepted or rolled-back plans are immutable; create a new pilot key"
                )
            row.client_reference = plan.client_reference
            row.environment = plan.environment
            row.contract_version = plan.contract_version
            row.release_revision = plan.release_revision
            row.plan_sha256 = digest
            row.owners = [
                item.model_dump(mode="json", exclude_none=True) for item in plan.owners
            ]
            row.access_grants = [
                item.model_dump(mode="json", exclude_none=True)
                for item in plan.access_grants
            ]
            row.field_policy = plan.field_policy.model_dump(mode="json")
            row.module_states = dict(plan.module_states)
            row.rollback_contract = plan.rollback_contract.model_dump(mode="json")
            row.submitted_at = plan.submitted_at
            row.updated_by_user_id = actor_user_id
            row.updated_at = datetime.now(UTC)
            row.state = "draft"
            event_type = "restaurant_pilot.plan_updated"
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type="restaurant_pilot_acceptance_plan",
                entity_id=row.id,
                payload={
                    "pilot_key": plan.pilot_key,
                    "client_reference_hash": plan_hash(
                        plan.model_copy(update={"client_reference": "redacted"})
                    ),
                    "plan_sha256": digest,
                    "live_activation_allowed": False,
                    "live_activation_performed": False,
                },
            )
        )
        await session.commit()
        return row

    async def upsert_check(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        check: PilotAcceptanceCheck,
    ) -> RestaurantPilotAcceptanceCheckRecord:
        plan = await self._plan(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
        )
        if plan.state in {"external_acceptance_recorded", "rolled_back"}:
            raise RestaurantPilotServiceError("Finalized pilot checks are immutable")
        row = await session.scalar(
            select(RestaurantPilotAcceptanceCheckRecord).where(
                RestaurantPilotAcceptanceCheckRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptanceCheckRecord.plan_id == plan_id,
                RestaurantPilotAcceptanceCheckRecord.check_key == check.check_key,
            )
        )
        now = datetime.now(UTC)
        if row is None:
            row = RestaurantPilotAcceptanceCheckRecord(
                workspace_id=workspace_id,
                plan_id=plan_id,
                check_key=check.check_key,
                category=check.category,
                state=check.state,
                evidence_reference=check.evidence_reference,
                evidence_sha256=check.evidence_sha256,
                observed_at=check.observed_at,
                expires_at=check.expires_at,
                reviewer_role=check.reviewer_role,
                reviewer_reference=check.reviewer_reference,
                details=dict(check.details),
                updated_by_user_id=actor_user_id,
                updated_at=now,
            )
            session.add(row)
        else:
            row.category = check.category
            row.state = check.state
            row.evidence_reference = check.evidence_reference
            row.evidence_sha256 = check.evidence_sha256
            row.observed_at = check.observed_at
            row.expires_at = check.expires_at
            row.reviewer_role = check.reviewer_role
            row.reviewer_reference = check.reviewer_reference
            row.details = dict(check.details)
            row.updated_by_user_id = actor_user_id
            row.updated_at = now
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="restaurant_pilot.check_recorded",
                entity_type="restaurant_pilot_acceptance_check",
                entity_id=row.id,
                payload={
                    "plan_id": str(plan_id),
                    "check_key": check.check_key,
                    "state": check.state,
                    "evidence_sha256": check.evidence_sha256,
                    "live_activation_performed": False,
                },
            )
        )
        await session.commit()
        return row

    async def readiness(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan_id: uuid.UUID,
        evaluated_at: datetime | None = None,
    ) -> PilotReadiness:
        plan_row = await self._plan(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
        )
        plan = self.plan_contract(plan_row)
        check_rows = (
            await session.scalars(
                select(RestaurantPilotAcceptanceCheckRecord)
                .where(
                    RestaurantPilotAcceptanceCheckRecord.workspace_id == workspace_id,
                    RestaurantPilotAcceptanceCheckRecord.plan_id == plan_id,
                )
                .order_by(RestaurantPilotAcceptanceCheckRecord.check_key)
            )
        ).all()
        checks = tuple(self.check_contract(row) for row in check_rows)
        external_acceptance = await session.scalar(
            select(RestaurantPilotAcceptanceDecisionRecord.id).where(
                RestaurantPilotAcceptanceDecisionRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptanceDecisionRecord.plan_id == plan_id,
                RestaurantPilotAcceptanceDecisionRecord.decision
                == "record_external_acceptance",
            )
        )
        result = evaluate_pilot_readiness(
            plan,
            checks,
            external_acceptance_recorded=external_acceptance is not None,
            evaluated_at=evaluated_at,
        )
        if result.state == "blocked":
            plan_row.state = "blocked"
        elif result.state == "ready_for_external_acceptance":
            plan_row.state = "ready_for_external_acceptance"
        else:
            plan_row.state = "external_acceptance_recorded"
        plan_row.updated_at = datetime.now(UTC)
        await session.commit()
        return result

    async def record_decision(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        decision: PilotAcceptanceDecision,
    ) -> RestaurantPilotAcceptanceDecisionRecord:
        plan = await self._plan(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
        )
        readiness = await self.readiness(
            session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            evaluated_at=decision.decided_at,
        )
        if decision.repository_readiness_sha256 != readiness.readiness_sha256:
            raise RestaurantPilotServiceError("Decision readiness hash is stale")
        if decision.decision in {
            "request_external_acceptance",
            "record_external_acceptance",
        } and readiness.state == "blocked":
            raise RestaurantPilotServiceError("Blocked pilot cannot request acceptance")
        if decision.decision == "record_external_acceptance":
            if readiness.state != "ready_for_external_acceptance":
                raise RestaurantPilotServiceError(
                    "External acceptance may be recorded once per ready plan"
                )
            plan.state = "external_acceptance_recorded"
        elif decision.decision == "request_external_acceptance":
            plan.state = "ready_for_external_acceptance"
        elif decision.decision == "reject":
            plan.state = "rejected"
        else:
            plan.state = "rolled_back"
        row = RestaurantPilotAcceptanceDecisionRecord(
            workspace_id=workspace_id,
            plan_id=plan_id,
            decision=decision.decision,
            repository_readiness_sha256=decision.repository_readiness_sha256,
            external_authorization_reference=decision.external_authorization_reference,
            external_authorization_sha256=decision.external_authorization_sha256,
            decision_note=decision.decision_note,
            decided_by_user_id=actor_user_id,
            decided_at=decision.decided_at,
            live_activation_performed=False,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="restaurant_pilot.decision_recorded",
                entity_type="restaurant_pilot_acceptance_decision",
                entity_id=row.id,
                payload={
                    "plan_id": str(plan_id),
                    "decision": decision.decision,
                    "repository_readiness_sha256": decision.repository_readiness_sha256,
                    "external_authorization_sha256": decision.external_authorization_sha256,
                    "live_activation_allowed": False,
                    "live_activation_performed": False,
                },
            )
        )
        await session.commit()
        return row

    async def record_disconnect_run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        run: PilotDisconnectRun,
    ) -> RestaurantPilotDisconnectRunRecord:
        await self._plan(session, workspace_id=workspace_id, plan_id=plan_id)
        existing = await session.scalar(
            select(RestaurantPilotDisconnectRunRecord).where(
                RestaurantPilotDisconnectRunRecord.workspace_id == workspace_id,
                RestaurantPilotDisconnectRunRecord.idempotency_key == run.idempotency_key,
            )
        )
        if existing is not None:
            return existing
        row = RestaurantPilotDisconnectRunRecord(
            workspace_id=workspace_id,
            plan_id=plan_id,
            idempotency_key=run.idempotency_key,
            state=run.state,
            started_at=run.started_at,
            completed_at=run.completed_at,
            evidence_reference=run.evidence_reference,
            evidence_sha256=run.evidence_sha256,
            ordering_impact_observed=False,
            deployment_impact_observed=False,
            source_access_revoked=run.source_access_revoked,
            provider_access_revoked=run.provider_access_revoked,
            summary=dict(run.summary),
            recorded_by_user_id=actor_user_id,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="restaurant_pilot.disconnect_recorded",
                entity_type="restaurant_pilot_disconnect_run",
                entity_id=row.id,
                payload={
                    "plan_id": str(plan_id),
                    "state": run.state,
                    "ordering_impact_observed": False,
                    "deployment_impact_observed": False,
                    "source_access_revoked": run.source_access_revoked,
                    "provider_access_revoked": run.provider_access_revoked,
                },
            )
        )
        await session.commit()
        return row

    async def _plan(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan_id: uuid.UUID,
    ) -> RestaurantPilotAcceptancePlanRecord:
        row = await session.scalar(
            select(RestaurantPilotAcceptancePlanRecord).where(
                RestaurantPilotAcceptancePlanRecord.workspace_id == workspace_id,
                RestaurantPilotAcceptancePlanRecord.id == plan_id,
            )
        )
        if row is None:
            raise RestaurantPilotServiceError("Restaurant pilot plan not found")
        return row

    @staticmethod
    def plan_contract(row: RestaurantPilotAcceptancePlanRecord) -> RestaurantPilotPlan:
        return RestaurantPilotPlan.model_validate(
            {
                "contract_version": row.contract_version,
                "pilot_key": row.pilot_key,
                "client_reference": row.client_reference,
                "environment": row.environment,
                "release_revision": row.release_revision,
                "owners": row.owners,
                "access_grants": row.access_grants,
                "field_policy": row.field_policy,
                "module_states": row.module_states,
                "rollback_contract": row.rollback_contract,
                "submitted_at": row.submitted_at,
            }
        )

    @staticmethod
    def check_contract(
        row: RestaurantPilotAcceptanceCheckRecord,
    ) -> PilotAcceptanceCheck:
        return PilotAcceptanceCheck.model_validate(
            {
                "check_key": row.check_key,
                "category": row.category,
                "state": row.state,
                "evidence_reference": row.evidence_reference,
                "evidence_sha256": row.evidence_sha256,
                "observed_at": row.observed_at,
                "expires_at": row.expires_at,
                "reviewer_role": row.reviewer_role,
                "reviewer_reference": row.reviewer_reference,
                "details": row.details,
            }
        )
