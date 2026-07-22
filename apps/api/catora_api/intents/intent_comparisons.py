from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import IntentSuiteRun
from catora_api.intents.coverage import IntentCoverageDataError
from catora_api.intents.intent_breakdown import (
    IntentCoverageMember,
    _child_runs,
    _match_snapshots,
    _suite_members,
    _suite_run,
    build_intent_coverage,
)
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    _validated_source,
)


@dataclass(frozen=True, slots=True)
class IntentCoverageByIntentComparisonReport:
    selected_run: IntentSuiteRun
    baseline_run: IntentSuiteRun
    selection_changed: bool
    items: tuple[IntentCoverageMember, ...]


class IntentCoverageByIntentComparisonService:
    async def compare(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        selected_suite_run_id: uuid.UUID,
        baseline_suite_run_id: uuid.UUID,
    ) -> IntentCoverageByIntentComparisonReport:
        if selected_suite_run_id == baseline_suite_run_id:
            raise IntentCoverageDataError(
                "An intent suite run cannot be compared with itself"
            )

        selected_run = await _suite_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_suite_run_id,
        )
        baseline_run = await _suite_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_suite_run_id,
        )
        if selected_run.intent_suite_id != baseline_run.intent_suite_id:
            raise IntentCoverageDataError(
                "Intent suite runs belong to different suites"
            )

        selected_products = _validated_products(selected_run, label="Selected")
        baseline_products = _validated_products(baseline_run, label="Baseline")
        members = await _suite_members(
            session,
            workspace_id=workspace_id,
            suite_id=selected_run.intent_suite_id,
        )
        selected_runs = await _child_runs(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_run.id,
        )
        selected_snapshots = await _match_snapshots(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_run.id,
        )
        baseline_runs = await _child_runs(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_run.id,
        )
        baseline_snapshots = await _match_snapshots(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_run.id,
        )
        items = build_intent_coverage(
            members,
            current_runs=selected_runs,
            current_snapshots=selected_snapshots,
            previous_runs=baseline_runs,
            previous_snapshots=baseline_snapshots,
        )
        return IntentCoverageByIntentComparisonReport(
            selected_run=selected_run,
            baseline_run=baseline_run,
            selection_changed=selected_products != baseline_products,
            items=items,
        )


def _validated_products(
    run: IntentSuiteRun,
    *,
    label: str,
) -> tuple[uuid.UUID, ...]:
    try:
        _snapshot_hash, product_ids = _validated_source(run)
    except IntentSuiteHistoryRerunConflictError as exc:
        raise IntentCoverageDataError(
            f"{label} intent suite run history is invalid: {exc}"
        ) from exc
    return product_ids
