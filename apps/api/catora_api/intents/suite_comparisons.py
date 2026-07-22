from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.intents.suite_reruns import _validated_source
from catora_api.intents.suites import (
    IntentSuiteRunDelta,
    IntentSuiteRunSummary,
    IntentSuiteService,
    PersistedIntentSuiteRun,
    coverage_basis_points,
    summary_delta,
)


class IntentSuiteRunComparisonError(RuntimeError):
    pass


class IntentSuiteRunComparisonConflictError(IntentSuiteRunComparisonError):
    pass


@dataclass(frozen=True, slots=True)
class IntentSuiteRunComparisonSide:
    persisted: PersistedIntentSuiteRun
    source_snapshot_hash: str
    product_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class IntentSuiteRunComparison:
    run: IntentSuiteRunComparisonSide
    baseline: IntentSuiteRunComparisonSide
    delta: IntentSuiteRunDelta

    @property
    def selection_changed(self) -> bool:
        return self.run.product_ids != self.baseline.product_ids


class IntentSuiteRunComparisonService:
    def __init__(self, suite_service: IntentSuiteService | None = None) -> None:
        self.suite_service = suite_service or IntentSuiteService()

    async def compare(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
        baseline_run_id: uuid.UUID,
    ) -> IntentSuiteRunComparison:
        if run_id == baseline_run_id:
            raise IntentSuiteRunComparisonConflictError(
                "A suite run cannot be compared with itself"
            )

        run = await self.suite_service.get_run(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        baseline = await self.suite_service.get_run(
            session,
            workspace_id=workspace_id,
            run_id=baseline_run_id,
        )
        if run.run.intent_suite_id != baseline.run.intent_suite_id:
            raise IntentSuiteRunComparisonConflictError(
                "Intent suite runs must belong to the same suite"
            )

        run_hash, run_product_ids = _validated_source(run.run)
        baseline_hash, baseline_product_ids = _validated_source(baseline.run)
        _validated_summary(run.summary)
        _validated_summary(baseline.summary)
        if run.summary.member_count != baseline.summary.member_count:
            raise IntentSuiteRunComparisonConflictError(
                "Intent suite run member counts do not reconcile"
            )

        return IntentSuiteRunComparison(
            run=IntentSuiteRunComparisonSide(
                persisted=run,
                source_snapshot_hash=run_hash,
                product_ids=run_product_ids,
            ),
            baseline=IntentSuiteRunComparisonSide(
                persisted=baseline,
                source_snapshot_hash=baseline_hash,
                product_ids=baseline_product_ids,
            ),
            delta=summary_delta(
                baseline.run.id,
                run.summary,
                baseline.summary,
            ),
        )


def _validated_summary(summary: IntentSuiteRunSummary) -> None:
    counts = (
        summary.confident_match_count,
        summary.possible_match_missing_data_count,
        summary.non_match_count,
        summary.insufficient_category_data_count,
    )
    numeric_values = (
        summary.member_count,
        summary.intent_run_count,
        summary.target_count,
        summary.product_count,
        *counts,
    )
    if any(value < 0 for value in numeric_values):
        raise IntentSuiteRunComparisonConflictError(
            "Intent suite run summary contains negative counts"
        )
    if summary.member_count < 1 or summary.intent_run_count != summary.member_count:
        raise IntentSuiteRunComparisonConflictError(
            "Intent suite run child counts do not reconcile"
        )
    if sum(counts) != summary.target_count:
        raise IntentSuiteRunComparisonConflictError(
            "Intent suite run match states do not reconcile"
        )
    if summary.product_count > summary.target_count:
        raise IntentSuiteRunComparisonConflictError(
            "Intent suite run product count exceeds its target count"
        )
    expected_coverage = coverage_basis_points(
        summary.confident_match_count,
        summary.target_count,
    )
    if summary.confident_coverage_basis_points != expected_coverage:
        raise IntentSuiteRunComparisonConflictError(
            "Intent suite run coverage does not reconcile"
        )
