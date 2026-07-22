from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import (
    IntentProductMatch,
    IntentRun,
    IntentSuiteRun,
)
from catora_api.intents.suites import coverage_basis_points
from catora_api.intents.types import IntentMatchResult

UNCLASSIFIED_CATEGORY_BUCKET = "_unclassified"


class IntentCoverageError(RuntimeError):
    pass


class IntentCoverageNotFoundError(IntentCoverageError):
    pass


class IntentCoverageStateError(IntentCoverageError):
    pass


class IntentCoverageDataError(IntentCoverageError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedMatchSnapshot:
    match_id: uuid.UUID
    intent_run_id: uuid.UUID
    buyer_intent_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    result: IntentMatchResult


@dataclass(frozen=True, slots=True)
class IntentCoverageTotals:
    intent_count: int
    target_count: int
    product_count: int
    confident_match_count: int
    possible_match_missing_data_count: int
    non_match_count: int
    insufficient_category_data_count: int
    confident_coverage_basis_points: int


@dataclass(frozen=True, slots=True)
class IntentCategoryCoverage:
    category_key: str | None
    intent_count: int
    target_count: int
    product_count: int
    confident_match_count: int
    possible_match_missing_data_count: int
    non_match_count: int
    insufficient_category_data_count: int
    confident_coverage_basis_points: int


@dataclass(frozen=True, slots=True)
class IntentCategoryCoverageReport:
    run: IntentSuiteRun
    items: tuple[IntentCategoryCoverage, ...]
    totals: IntentCoverageTotals


@dataclass(frozen=True, slots=True)
class IntentRemediationPriority:
    priority_rank: int
    field_key: str
    affected_intent_count: int
    affected_target_count: int
    affected_product_count: int
    intent_impact_basis_points: int
    target_impact_basis_points: int
    product_impact_basis_points: int
    missing_constraint_count: int
    conflicting_constraint_count: int
    category_keys: tuple[str, ...]
    unclassified_target_count: int


@dataclass(frozen=True, slots=True)
class IntentRemediationPage:
    run: IntentSuiteRun
    items: tuple[IntentRemediationPriority, ...]
    total: int
    scope: IntentCoverageTotals
    category_bucket: str | None


@dataclass(slots=True)
class _CoverageAccumulator:
    intent_ids: set[uuid.UUID] = field(default_factory=set)
    product_ids: set[uuid.UUID] = field(default_factory=set)
    status_counts: defaultdict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    target_count: int = 0


@dataclass(slots=True)
class _RemediationAccumulator:
    intent_ids: set[uuid.UUID] = field(default_factory=set)
    target_ids: set[uuid.UUID] = field(default_factory=set)
    product_ids: set[uuid.UUID] = field(default_factory=set)
    category_keys: set[str] = field(default_factory=set)
    unclassified_target_ids: set[uuid.UUID] = field(default_factory=set)
    missing_constraint_count: int = 0
    conflicting_constraint_count: int = 0


class IntentCoverageService:
    async def category_coverage(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentCategoryCoverageReport:
        run, snapshots = await self._load(
            session,
            workspace_id=workspace_id,
            suite_run_id=suite_run_id,
        )
        return IntentCategoryCoverageReport(
            run=run,
            items=build_category_coverage(snapshots),
            totals=coverage_totals(snapshots),
        )

    async def remediations(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
        category_bucket: str | None,
        offset: int,
        limit: int,
    ) -> IntentRemediationPage:
        run, snapshots = await self._load(
            session,
            workspace_id=workspace_id,
            suite_run_id=suite_run_id,
        )
        selected = filter_category_snapshots(snapshots, category_bucket)
        items = build_remediation_priorities(selected)
        return IntentRemediationPage(
            run=run,
            items=items[offset : offset + limit],
            total=len(items),
            scope=coverage_totals(selected),
            category_bucket=category_bucket,
        )

    async def _load(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> tuple[IntentSuiteRun, tuple[PersistedMatchSnapshot, ...]]:
        run = await session.scalar(
            select(IntentSuiteRun).where(
                IntentSuiteRun.id == suite_run_id,
                IntentSuiteRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise IntentCoverageNotFoundError("Intent suite run not found")
        if run.status != "completed":
            raise IntentCoverageStateError("Intent suite run is not completed")
        if run.source_snapshot_hash is None:
            raise IntentCoverageDataError(
                "Completed intent suite run has no source snapshot hash"
            )
        rows = (
            await session.execute(
                select(IntentProductMatch, IntentRun.buyer_intent_id)
                .join(IntentRun, IntentRun.id == IntentProductMatch.intent_run_id)
                .where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.intent_suite_run_id == suite_run_id,
                )
                .order_by(
                    IntentRun.id,
                    IntentProductMatch.product_id,
                    IntentProductMatch.variant_id.asc().nulls_first(),
                    IntentProductMatch.id,
                )
            )
        ).all()
        snapshots = tuple(
            persisted_match_snapshot(match, buyer_intent_id)
            for match, buyer_intent_id in rows
        )
        match_ids = [item.match_id for item in snapshots]
        if len(match_ids) != len(set(match_ids)):
            raise IntentCoverageDataError("Duplicate persisted match rows were loaded")
        return run, snapshots


def persisted_match_snapshot(
    match: IntentProductMatch,
    buyer_intent_id: uuid.UUID,
) -> PersistedMatchSnapshot:
    if "category_key" not in match.explanation:
        raise IntentCoverageDataError("Stored intent match explanation is invalid")
    try:
        result = IntentMatchResult.model_validate(match.explanation)
    except ValidationError as exc:
        raise IntentCoverageDataError("Stored intent match explanation is invalid") from exc
    if result.product_id != match.product_id:
        raise IntentCoverageDataError("Stored intent match product identity does not reconcile")
    if result.variant_id != match.variant_id:
        raise IntentCoverageDataError("Stored intent match variant identity does not reconcile")
    if result.status != match.status:
        raise IntentCoverageDataError("Stored intent match status does not reconcile")
    _validate_result_fields(result)
    return PersistedMatchSnapshot(
        match_id=match.id,
        intent_run_id=match.intent_run_id,
        buyer_intent_id=buyer_intent_id,
        product_id=match.product_id,
        variant_id=match.variant_id,
        result=result,
    )


def _validate_result_fields(result: IntentMatchResult) -> None:
    missing = {
        item.field_key
        for item in result.hard_constraints
        if item.status in {"missing", "conflicting"}
    }
    violated = {
        item.field_key
        for item in result.hard_constraints
        if item.status == "violated"
    }
    if missing != set(result.missing_fields):
        raise IntentCoverageDataError("Stored intent match missing fields do not reconcile")
    if violated != set(result.violated_fields):
        raise IntentCoverageDataError("Stored intent match violated fields do not reconcile")
    if result.status == "possible_match_missing_data" and not missing:
        raise IntentCoverageDataError(
            "Possible-match result has no missing or conflicting hard constraint"
        )
    if result.category_status == "missing" and result.category_key is not None:
        raise IntentCoverageDataError("Missing category status carries a category key")
    if result.category_status in {"supported", "violated"} and result.category_key is None:
        raise IntentCoverageDataError("Known category status has no category key")
    if (
        result.category_status == "missing"
        and result.status != "insufficient_category_data"
    ):
        raise IntentCoverageDataError("Missing category status has an invalid match status")
    if result.category_status == "violated" and result.status != "non_match":
        raise IntentCoverageDataError("Violated category status has an invalid match status")


def coverage_totals(
    snapshots: tuple[PersistedMatchSnapshot, ...],
) -> IntentCoverageTotals:
    accumulator = _CoverageAccumulator()
    for snapshot in snapshots:
        _add_coverage(accumulator, snapshot)
    return _coverage_totals(accumulator)


def build_category_coverage(
    snapshots: tuple[PersistedMatchSnapshot, ...],
) -> tuple[IntentCategoryCoverage, ...]:
    groups: dict[str | None, _CoverageAccumulator] = {}
    for snapshot in snapshots:
        category_key = snapshot.result.category_key
        accumulator = groups.setdefault(category_key, _CoverageAccumulator())
        _add_coverage(accumulator, snapshot)
    items = [
        _category_coverage(category_key, accumulator)
        for category_key, accumulator in groups.items()
    ]
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.category_key is None,
                item.category_key or "",
            ),
        )
    )


def _add_coverage(
    accumulator: _CoverageAccumulator,
    snapshot: PersistedMatchSnapshot,
) -> None:
    accumulator.intent_ids.add(snapshot.buyer_intent_id)
    accumulator.product_ids.add(snapshot.product_id)
    accumulator.status_counts[snapshot.result.status] += 1
    accumulator.target_count += 1


def _coverage_totals(accumulator: _CoverageAccumulator) -> IntentCoverageTotals:
    counts = accumulator.status_counts
    return IntentCoverageTotals(
        intent_count=len(accumulator.intent_ids),
        target_count=accumulator.target_count,
        product_count=len(accumulator.product_ids),
        confident_match_count=counts["confident_match"],
        possible_match_missing_data_count=counts["possible_match_missing_data"],
        non_match_count=counts["non_match"],
        insufficient_category_data_count=counts["insufficient_category_data"],
        confident_coverage_basis_points=coverage_basis_points(
            counts["confident_match"],
            accumulator.target_count,
        ),
    )


def _category_coverage(
    category_key: str | None,
    accumulator: _CoverageAccumulator,
) -> IntentCategoryCoverage:
    totals = _coverage_totals(accumulator)
    return IntentCategoryCoverage(
        category_key=category_key,
        intent_count=totals.intent_count,
        target_count=totals.target_count,
        product_count=totals.product_count,
        confident_match_count=totals.confident_match_count,
        possible_match_missing_data_count=(
            totals.possible_match_missing_data_count
        ),
        non_match_count=totals.non_match_count,
        insufficient_category_data_count=(
            totals.insufficient_category_data_count
        ),
        confident_coverage_basis_points=totals.confident_coverage_basis_points,
    )


def filter_category_snapshots(
    snapshots: tuple[PersistedMatchSnapshot, ...],
    category_bucket: str | None,
) -> tuple[PersistedMatchSnapshot, ...]:
    if category_bucket is None:
        return snapshots
    if category_bucket == UNCLASSIFIED_CATEGORY_BUCKET:
        return tuple(item for item in snapshots if item.result.category_key is None)
    return tuple(
        item for item in snapshots if item.result.category_key == category_bucket
    )


def build_remediation_priorities(
    snapshots: tuple[PersistedMatchSnapshot, ...],
) -> tuple[IntentRemediationPriority, ...]:
    total_intents = len({item.buyer_intent_id for item in snapshots})
    total_targets = len(snapshots)
    total_products = len({item.product_id for item in snapshots})
    groups: dict[str, _RemediationAccumulator] = {}
    for snapshot in snapshots:
        result = snapshot.result
        if result.status != "possible_match_missing_data":
            continue
        evaluations: defaultdict[str, list[str]] = defaultdict(list)
        for item in result.hard_constraints:
            if item.status in {"missing", "conflicting"}:
                evaluations[item.field_key].append(item.status)
        if set(evaluations) != set(result.missing_fields):
            raise IntentCoverageDataError(
                "Stored remediation fields do not reconcile with constraints"
            )
        for field_key in result.missing_fields:
            accumulator = groups.setdefault(field_key, _RemediationAccumulator())
            accumulator.intent_ids.add(snapshot.buyer_intent_id)
            accumulator.target_ids.add(snapshot.match_id)
            accumulator.product_ids.add(snapshot.product_id)
            if result.category_key is None:
                accumulator.unclassified_target_ids.add(snapshot.match_id)
            else:
                accumulator.category_keys.add(result.category_key)
            for constraint_status in evaluations[field_key]:
                if constraint_status == "missing":
                    accumulator.missing_constraint_count += 1
                else:
                    accumulator.conflicting_constraint_count += 1

    ordered = sorted(
        groups.items(),
        key=lambda item: (
            -len(item[1].intent_ids),
            -len(item[1].product_ids),
            -len(item[1].target_ids),
            item[0],
        ),
    )
    return tuple(
        IntentRemediationPriority(
            priority_rank=rank,
            field_key=field_key,
            affected_intent_count=len(accumulator.intent_ids),
            affected_target_count=len(accumulator.target_ids),
            affected_product_count=len(accumulator.product_ids),
            intent_impact_basis_points=coverage_basis_points(
                len(accumulator.intent_ids),
                total_intents,
            ),
            target_impact_basis_points=coverage_basis_points(
                len(accumulator.target_ids),
                total_targets,
            ),
            product_impact_basis_points=coverage_basis_points(
                len(accumulator.product_ids),
                total_products,
            ),
            missing_constraint_count=accumulator.missing_constraint_count,
            conflicting_constraint_count=accumulator.conflicting_constraint_count,
            category_keys=tuple(sorted(accumulator.category_keys)),
            unclassified_target_count=len(accumulator.unclassified_target_ids),
        )
        for rank, (field_key, accumulator) in enumerate(ordered, start=1)
    )
