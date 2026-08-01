from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import AuditEvent
from catora_api.db.models.restaurant_answers import (
    RestaurantAnswerResult,
    RestaurantAnswerRun,
    RestaurantAnswerSuiteVersion,
    RestaurantExternalCitationObservation,
)
from catora_api.restaurant_answers.evaluator import (
    evaluate_restaurant_questions,
    restaurant_question_suite,
)
from catora_api.restaurant_answers.models import (
    ExternalCitationObservation,
    RestaurantAnswerRunSnapshot,
    RestaurantFactEvidence,
)


class RestaurantAnswerEvaluationError(RuntimeError):
    pass


class RestaurantAnswerEvaluationService:
    async def run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        evidence: tuple[RestaurantFactEvidence, ...],
        idempotency_key: str,
        as_of: datetime | None = None,
    ) -> tuple[RestaurantAnswerRun, RestaurantAnswerRunSnapshot]:
        suite = restaurant_question_suite()
        snapshot = evaluate_restaurant_questions(
            entity_type=entity_type,
            entity_id=entity_id,
            evidence=evidence,
            as_of=as_of,
            suite=suite,
        )
        existing = await session.scalar(
            select(RestaurantAnswerRun).where(
                RestaurantAnswerRun.workspace_id == workspace_id,
                RestaurantAnswerRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.input_sha256 != snapshot.input_sha256:
                raise RestaurantAnswerEvaluationError(
                    "Idempotency key was already used for different evidence"
                )
            return existing, await self.snapshot(session, workspace_id, existing.id)

        suite_row = await self._suite_version(session, workspace_id=workspace_id)
        run = RestaurantAnswerRun(
            workspace_id=workspace_id,
            suite_version_id=suite_row.id,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            input_sha256=snapshot.input_sha256,
            status="completed",
            evaluated_at=snapshot.evaluated_at,
            state_counts=dict(snapshot.state_counts),
            input_snapshot={
                "contract_version": snapshot.contract_version,
                "suite_key": snapshot.suite_key,
                "suite_version": snapshot.suite_version,
                "suite_sha256": snapshot.suite_sha256,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "evidence": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in evidence
                ],
            },
        )
        session.add(run)
        await session.flush()
        for result in snapshot.results:
            session.add(
                RestaurantAnswerResult(
                    workspace_id=workspace_id,
                    run_id=run.id,
                    question_key=result.question_key,
                    question=result.question,
                    state=result.state,
                    rationale=result.rationale,
                    fact_keys=list(result.fact_keys),
                    evidence_ids=[str(value) for value in result.evidence_ids],
                    evaluated_at=result.evaluated_at,
                )
            )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="restaurant.answer_evaluation_completed",
                entity_type="restaurant_answer_run",
                entity_id=run.id,
                payload={
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "suite_sha256": snapshot.suite_sha256,
                    "input_sha256": snapshot.input_sha256,
                    "state_counts": dict(snapshot.state_counts),
                },
            )
        )
        await session.commit()
        return run, snapshot

    async def snapshot(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> RestaurantAnswerRunSnapshot:
        run = await session.scalar(
            select(RestaurantAnswerRun).where(
                RestaurantAnswerRun.id == run_id,
                RestaurantAnswerRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise RestaurantAnswerEvaluationError("Restaurant answer run not found")
        rows = (
            await session.scalars(
                select(RestaurantAnswerResult)
                .where(
                    RestaurantAnswerResult.run_id == run.id,
                    RestaurantAnswerResult.workspace_id == workspace_id,
                )
                .order_by(RestaurantAnswerResult.question_key)
            )
        ).all()
        from catora_api.restaurant_answers.models import RestaurantQuestionEvaluation

        results = tuple(
            RestaurantQuestionEvaluation(
                question_key=row.question_key,
                question=row.question,
                entity_type=run.entity_type,  # type: ignore[arg-type]
                entity_id=run.entity_id,
                state=row.state,  # type: ignore[arg-type]
                rationale=row.rationale,
                evidence_ids=tuple(uuid.UUID(value) for value in row.evidence_ids),
                fact_keys=tuple(row.fact_keys),
                evaluated_at=row.evaluated_at,
            )
            for row in rows
        )
        input_snapshot = dict(run.input_snapshot)
        return RestaurantAnswerRunSnapshot(
            suite_key=str(input_snapshot["suite_key"]),
            suite_version=str(input_snapshot["suite_version"]),
            suite_sha256=str(input_snapshot["suite_sha256"]),
            entity_type=run.entity_type,  # type: ignore[arg-type]
            entity_id=run.entity_id,
            evaluated_at=run.evaluated_at,
            results=results,
            state_counts=dict(run.state_counts),  # type: ignore[arg-type]
            input_sha256=run.input_sha256,
        )

    async def record_external_observation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        observation: ExternalCitationObservation,
        provider_cost_microunits: int | None = None,
    ) -> RestaurantExternalCitationObservation:
        if provider_cost_microunits is not None and provider_cost_microunits < 0:
            raise RestaurantAnswerEvaluationError("Provider cost cannot be negative")
        row = RestaurantExternalCitationObservation(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            provider=observation.provider,
            model_or_surface=observation.model_or_surface,
            locale=observation.locale,
            exact_query=observation.exact_query,
            observed_at=observation.observed_at,
            response_sha256=observation.response_sha256,
            cited_urls=list(observation.cited_urls),
            accuracy_state=observation.accuracy_state,
            verified_fact_keys=list(observation.verified_fact_keys),
            notes=observation.notes,
            provider_cost_microunits=provider_cost_microunits,
        )
        session.add(row)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                event_type="restaurant.external_citation_observation_recorded",
                entity_type="restaurant_external_citation_observation",
                entity_id=row.id,
                payload={
                    "provider": observation.provider,
                    "model_or_surface": observation.model_or_surface,
                    "accuracy_state": observation.accuracy_state,
                    "citation_count": len(observation.cited_urls),
                },
            )
        )
        await session.commit()
        return row

    async def _suite_version(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
    ) -> RestaurantAnswerSuiteVersion:
        suite = restaurant_question_suite()
        existing = await session.scalar(
            select(RestaurantAnswerSuiteVersion).where(
                RestaurantAnswerSuiteVersion.workspace_id == workspace_id,
                RestaurantAnswerSuiteVersion.suite_sha256 == suite.suite_sha256,
            )
        )
        if existing is not None:
            return existing
        row = RestaurantAnswerSuiteVersion(
            workspace_id=workspace_id,
            suite_key=suite.suite_key,
            suite_version=suite.suite_version,
            suite_sha256=suite.suite_sha256,
            definition=suite.model_dump(mode="json"),
        )
        session.add(row)
        await session.flush()
        return row
