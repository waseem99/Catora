from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import (
    BuyerIntent,
    IntentProductMatch,
    IntentRun,
    IntentSuiteMember,
    IntentSuiteRun,
)
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageStateError,
    IntentCoverageTotals,
    PersistedMatchSnapshot,
    coverage_totals,
    persisted_match_snapshot,
)
from catora_api.intents.types import StructuredBuyerIntent

_ALLOWED_SOURCES = {"template", "user_entered", "ai_assisted"}


@dataclass(frozen=True, slots=True)
class IntentCoverageMember:
    member: IntentSuiteMember
    intent: BuyerIntent
    intent_run: IntentRun
    category_keys: tuple[str, ...]
    summary: IntentCoverageTotals
    delta: IntentCoverageMemberDelta | None


@dataclass(frozen=True, slots=True)
class IntentCoverageMemberDelta:
    previous_intent_run_id: uuid.UUID
    target_count_delta: int
    product_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


@dataclass(frozen=True, slots=True)
class IntentCoverageByIntentReport:
    run: IntentSuiteRun
    items: tuple[IntentCoverageMember, ...]


class IntentCoverageByIntentService:
    async def report(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_run_id: uuid.UUID,
    ) -> IntentCoverageByIntentReport:
        run = await _suite_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=suite_run_id,
        )
        members = await _suite_members(
            session,
            workspace_id=workspace_id,
            suite_id=run.intent_suite_id,
        )
        current_runs = await _child_runs(
            session,
            workspace_id=workspace_id,
            suite_run_id=run.id,
        )
        current_snapshots = await _match_snapshots(
            session,
            workspace_id=workspace_id,
            suite_run_id=run.id,
        )

        previous_runs: tuple[IntentRun, ...] = ()
        previous_snapshots: tuple[PersistedMatchSnapshot, ...] = ()
        if run.previous_run_id is not None:
            previous = await _suite_run(
                session,
                workspace_id=workspace_id,
                suite_run_id=run.previous_run_id,
            )
            if previous.intent_suite_id != run.intent_suite_id:
                raise IntentCoverageDataError(
                    "Previous intent suite run belongs to another suite"
                )
            previous_runs = await _child_runs(
                session,
                workspace_id=workspace_id,
                suite_run_id=previous.id,
            )
            previous_snapshots = await _match_snapshots(
                session,
                workspace_id=workspace_id,
                suite_run_id=previous.id,
            )

        items = build_intent_coverage(
            members,
            current_runs=current_runs,
            current_snapshots=current_snapshots,
            previous_runs=previous_runs,
            previous_snapshots=previous_snapshots,
        )
        return IntentCoverageByIntentReport(run=run, items=items)


async def _suite_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
) -> IntentSuiteRun:
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
    return run


async def _suite_members(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
) -> tuple[tuple[IntentSuiteMember, BuyerIntent], ...]:
    rows = (
        await session.execute(
            select(IntentSuiteMember, BuyerIntent)
            .join(BuyerIntent, BuyerIntent.id == IntentSuiteMember.buyer_intent_id)
            .where(
                IntentSuiteMember.workspace_id == workspace_id,
                IntentSuiteMember.intent_suite_id == suite_id,
                BuyerIntent.workspace_id == workspace_id,
            )
            .order_by(IntentSuiteMember.position, IntentSuiteMember.id)
        )
    ).all()
    members = tuple((row[0], row[1]) for row in rows)
    if not members:
        raise IntentCoverageDataError("Intent suite has no members")
    positions = tuple(member.position for member, _intent in members)
    if positions != tuple(range(len(members))):
        raise IntentCoverageDataError("Intent suite member positions are not contiguous")
    intent_ids = [intent.id for _member, intent in members]
    if len(intent_ids) != len(set(intent_ids)):
        raise IntentCoverageDataError("Intent suite contains duplicate buyer intents")
    return members


async def _child_runs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
) -> tuple[IntentRun, ...]:
    return tuple(
        (
            await session.scalars(
                select(IntentRun)
                .where(
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.intent_suite_run_id == suite_run_id,
                )
                .order_by(IntentRun.buyer_intent_id, IntentRun.id)
            )
        ).all()
    )


async def _match_snapshots(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
) -> tuple[PersistedMatchSnapshot, ...]:
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
    return tuple(
        persisted_match_snapshot(match, buyer_intent_id)
        for match, buyer_intent_id in rows
    )


def build_intent_coverage(
    members: tuple[tuple[IntentSuiteMember, BuyerIntent], ...],
    *,
    current_runs: tuple[IntentRun, ...],
    current_snapshots: tuple[PersistedMatchSnapshot, ...],
    previous_runs: tuple[IntentRun, ...] = (),
    previous_snapshots: tuple[PersistedMatchSnapshot, ...] = (),
) -> tuple[IntentCoverageMember, ...]:
    member_intent_ids = tuple(intent.id for _member, intent in members)
    current_by_intent = _run_map(
        current_runs,
        expected_intent_ids=member_intent_ids,
        label="Current",
    )
    previous_by_intent: dict[uuid.UUID, IntentRun] = {}
    if previous_runs:
        previous_by_intent = _run_map(
            previous_runs,
            expected_intent_ids=member_intent_ids,
            label="Previous",
        )
    elif previous_snapshots:
        raise IntentCoverageDataError(
            "Previous intent matches exist without previous child runs"
        )

    current_by_run = _snapshot_groups(
        current_snapshots,
        current_runs,
        label="Current",
    )
    previous_by_run = _snapshot_groups(
        previous_snapshots,
        previous_runs,
        label="Previous",
    )

    items: list[IntentCoverageMember] = []
    for member, intent in members:
        if intent.source not in _ALLOWED_SOURCES:
            raise IntentCoverageDataError("Buyer intent source is invalid")
        try:
            structured = StructuredBuyerIntent.model_validate(intent.structured_intent)
        except ValidationError as exc:
            raise IntentCoverageDataError(
                "Stored structured buyer intent is invalid"
            ) from exc
        current_run = current_by_intent[intent.id]
        current_summary = coverage_totals(
            current_by_run.get(current_run.id, ())
        )
        delta = None
        if previous_by_intent:
            previous_run = previous_by_intent[intent.id]
            previous_summary = coverage_totals(
                previous_by_run.get(previous_run.id, ())
            )
            delta = intent_coverage_delta(
                previous_run.id,
                current=current_summary,
                previous=previous_summary,
            )
        items.append(
            IntentCoverageMember(
                member=member,
                intent=intent,
                intent_run=current_run,
                category_keys=structured.category_keys,
                summary=current_summary,
                delta=delta,
            )
        )
    return tuple(items)


def _run_map(
    runs: tuple[IntentRun, ...],
    *,
    expected_intent_ids: tuple[uuid.UUID, ...],
    label: str,
) -> dict[uuid.UUID, IntentRun]:
    by_intent: dict[uuid.UUID, IntentRun] = {}
    for run in runs:
        if run.status != "completed":
            raise IntentCoverageDataError(
                f"{label} intent suite child run is not completed"
            )
        if len(run.source_snapshot_hash) != 64:
            raise IntentCoverageDataError(
                f"{label} intent suite child run has an invalid snapshot hash"
            )
        if run.buyer_intent_id in by_intent:
            raise IntentCoverageDataError(
                f"{label} intent suite has duplicate child runs"
            )
        by_intent[run.buyer_intent_id] = run
    if set(by_intent) != set(expected_intent_ids):
        raise IntentCoverageDataError(
            f"{label} intent suite child runs do not match members"
        )
    return by_intent


def _snapshot_groups(
    snapshots: tuple[PersistedMatchSnapshot, ...],
    runs: tuple[IntentRun, ...],
    *,
    label: str,
) -> dict[uuid.UUID, tuple[PersistedMatchSnapshot, ...]]:
    runs_by_id = {run.id: run for run in runs}
    groups: defaultdict[uuid.UUID, list[PersistedMatchSnapshot]] = defaultdict(list)
    seen_match_ids: set[uuid.UUID] = set()
    for snapshot in snapshots:
        if snapshot.match_id in seen_match_ids:
            raise IntentCoverageDataError(f"{label} intent matches contain duplicates")
        seen_match_ids.add(snapshot.match_id)
        run = runs_by_id.get(snapshot.intent_run_id)
        if run is None:
            raise IntentCoverageDataError(
                f"{label} intent match references an unknown child run"
            )
        if snapshot.buyer_intent_id != run.buyer_intent_id:
            raise IntentCoverageDataError(
                f"{label} intent match does not reconcile with its child run"
            )
        groups[run.id].append(snapshot)
    return {
        run_id: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.product_id,
                    item.variant_id is not None,
                    item.variant_id or uuid.UUID(int=0),
                    item.match_id,
                ),
            )
        )
        for run_id, values in groups.items()
    }


def intent_coverage_delta(
    previous_intent_run_id: uuid.UUID,
    *,
    current: IntentCoverageTotals,
    previous: IntentCoverageTotals,
) -> IntentCoverageMemberDelta:
    return IntentCoverageMemberDelta(
        previous_intent_run_id=previous_intent_run_id,
        target_count_delta=current.target_count - previous.target_count,
        product_count_delta=current.product_count - previous.product_count,
        confident_match_count_delta=(
            current.confident_match_count - previous.confident_match_count
        ),
        possible_match_missing_data_count_delta=(
            current.possible_match_missing_data_count
            - previous.possible_match_missing_data_count
        ),
        non_match_count_delta=current.non_match_count - previous.non_match_count,
        insufficient_category_data_count_delta=(
            current.insufficient_category_data_count
            - previous.insufficient_category_data_count
        ),
        confident_coverage_basis_points_delta=(
            current.confident_coverage_basis_points
            - previous.confident_coverage_basis_points
        ),
    )
