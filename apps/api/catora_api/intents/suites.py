from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import (
    BuyerIntent,
    IntentProductMatch,
    IntentRun,
    IntentSuite,
    IntentSuiteMember,
    IntentSuiteRun,
)
from catora_api.intents.execution import IntentRunService, PersistedIntentRun


class IntentSuiteError(RuntimeError):
    pass


class IntentSuiteNotFoundError(IntentSuiteError):
    pass


class IntentSuiteMemberError(IntentSuiteError):
    pass


class _PinnedIntentSession:
    def __init__(self, session: AsyncSession, intent: BuyerIntent) -> None:
        self._session = session
        self._intent = intent
        self._served_intent = False

    async def scalar(
        self,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not self._served_intent:
            descriptions = getattr(statement, "column_descriptions", ())
            entity = descriptions[0].get("entity") if descriptions else None
            if entity is not BuyerIntent:
                raise IntentSuiteMemberError(
                    "Pinned intent execution contract changed unexpectedly"
                )
            self._served_intent = True
            return self._intent
        return await self._session.scalar(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


@dataclass(frozen=True, slots=True)
class IntentSuiteMemberRecord:
    member: IntentSuiteMember
    intent: BuyerIntent


@dataclass(frozen=True, slots=True)
class IntentSuiteRecord:
    suite: IntentSuite
    members: tuple[IntentSuiteMemberRecord, ...]


@dataclass(frozen=True, slots=True)
class IntentSuitePage:
    items: tuple[IntentSuiteRecord, ...]
    total: int


@dataclass(frozen=True, slots=True)
class IntentSuiteRunSummary:
    member_count: int
    intent_run_count: int
    target_count: int
    product_count: int
    confident_match_count: int
    possible_match_missing_data_count: int
    non_match_count: int
    insufficient_category_data_count: int
    confident_coverage_basis_points: int


@dataclass(frozen=True, slots=True)
class IntentSuiteRunDelta:
    previous_run_id: uuid.UUID
    target_count_delta: int
    confident_match_count_delta: int
    possible_match_missing_data_count_delta: int
    non_match_count_delta: int
    insufficient_category_data_count_delta: int
    confident_coverage_basis_points_delta: int


@dataclass(frozen=True, slots=True)
class PersistedIntentSuiteRun:
    run: IntentSuiteRun
    suite: IntentSuite
    child_runs: tuple[PersistedIntentRun, ...]
    child_run_ids: tuple[uuid.UUID, ...]
    summary: IntentSuiteRunSummary
    delta: IntentSuiteRunDelta | None


class IntentSuiteService:
    def __init__(self, run_service: IntentRunService | None = None) -> None:
        self.run_service = run_service or IntentRunService()

    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        name: str,
        description: str | None,
        members: tuple[tuple[uuid.UUID, int], ...],
    ) -> IntentSuiteRecord:
        if not members:
            raise IntentSuiteMemberError("Intent suites require at least one member")
        if len(members) != len(set(members)):
            raise IntentSuiteMemberError("Intent suite members must be unique")
        intents = tuple(
            (
                await session.scalars(
                    select(BuyerIntent)
                    .where(
                        BuyerIntent.workspace_id == workspace_id,
                        BuyerIntent.approval_status == "approved",
                        tuple_(BuyerIntent.lineage_id, BuyerIntent.version).in_(members),
                    )
                    .order_by(BuyerIntent.lineage_id, BuyerIntent.version)
                )
            ).all()
        )
        by_key = {(item.lineage_id, item.version): item for item in intents}
        if set(by_key) != set(members):
            raise IntentSuiteMemberError(
                "One or more approved buyer intent versions were not found"
            )

        suite = IntentSuite(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name=name,
            description=description,
        )
        session.add(suite)
        await session.flush()
        records: list[IntentSuiteMemberRecord] = []
        for position, key in enumerate(members):
            intent = by_key[key]
            member = IntentSuiteMember(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                intent_suite_id=suite.id,
                buyer_intent_id=intent.id,
                position=position,
            )
            session.add(member)
            records.append(IntentSuiteMemberRecord(member=member, intent=intent))
        await session.flush()
        return IntentSuiteRecord(suite=suite, members=tuple(records))

    async def list(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        offset: int,
        limit: int,
    ) -> IntentSuitePage:
        total = int(
            (
                await session.scalar(
                    select(func.count()).select_from(IntentSuite).where(
                        IntentSuite.workspace_id == workspace_id
                    )
                )
            )
            or 0
        )
        suites = tuple(
            (
                await session.scalars(
                    select(IntentSuite)
                    .where(IntentSuite.workspace_id == workspace_id)
                    .order_by(IntentSuite.created_at.desc(), IntentSuite.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        records = tuple(
            [
                await self.get(
                    session,
                    workspace_id=workspace_id,
                    suite_id=suite.id,
                )
                for suite in suites
            ]
        )
        return IntentSuitePage(items=records, total=total)

    async def get(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_id: uuid.UUID,
    ) -> IntentSuiteRecord:
        suite = await session.scalar(
            select(IntentSuite).where(
                IntentSuite.id == suite_id,
                IntentSuite.workspace_id == workspace_id,
            )
        )
        if suite is None:
            raise IntentSuiteNotFoundError("Intent suite not found")
        rows = (
            await session.execute(
                select(IntentSuiteMember, BuyerIntent)
                .join(BuyerIntent, BuyerIntent.id == IntentSuiteMember.buyer_intent_id)
                .where(
                    IntentSuiteMember.intent_suite_id == suite_id,
                    IntentSuiteMember.workspace_id == workspace_id,
                    BuyerIntent.workspace_id == workspace_id,
                )
                .order_by(IntentSuiteMember.position, IntentSuiteMember.id)
            )
        ).all()
        members = tuple(
            IntentSuiteMemberRecord(member=row[0], intent=row[1]) for row in rows
        )
        if not members:
            raise IntentSuiteMemberError("Intent suite has no members")
        return IntentSuiteRecord(suite=suite, members=members)

    async def execute(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_id: uuid.UUID,
        product_ids: tuple[uuid.UUID, ...] = (),
    ) -> PersistedIntentSuiteRun:
        if len(product_ids) != len(set(product_ids)):
            raise IntentSuiteMemberError("Intent-suite product identifiers must be unique")
        record = await self.get(
            session,
            workspace_id=workspace_id,
            suite_id=suite_id,
        )
        previous = await session.scalar(
            select(IntentSuiteRun)
            .where(
                IntentSuiteRun.workspace_id == workspace_id,
                IntentSuiteRun.intent_suite_id == suite_id,
                IntentSuiteRun.status == "completed",
            )
            .order_by(
                IntentSuiteRun.completed_at.desc().nulls_last(),
                IntentSuiteRun.id.desc(),
            )
            .limit(1)
        )
        run = IntentSuiteRun(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            intent_suite_id=suite_id,
            previous_run_id=previous.id if previous is not None else None,
            status="running",
            requested_product_ids=[str(item) for item in sorted(product_ids)],
            source_snapshot_hash=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        session.add(run)

        child_runs: list[PersistedIntentRun] = []
        for member in record.members:
            if member.intent.approval_status not in {"approved", "superseded"}:
                raise IntentSuiteMemberError(
                    "Intent suite member is no longer an approved version"
                )
            pinned_session = cast(
                AsyncSession,
                _PinnedIntentSession(session, member.intent),
            )
            child = await self.run_service.execute(
                pinned_session,
                workspace_id=workspace_id,
                lineage_id=member.intent.lineage_id,
                intent_version=member.intent.version,
                product_ids=product_ids,
            )
            child.run.intent_suite_run_id = run.id
            child_runs.append(child)
        await session.flush()

        summary = await _suite_summary(
            session,
            workspace_id=workspace_id,
            suite_run_id=run.id,
            member_count=len(record.members),
        )
        run.source_snapshot_hash = suite_snapshot_hash(
            record,
            product_ids=product_ids,
            child_runs=tuple(child_runs),
        )
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.flush()

        delta = None
        if previous is not None:
            previous_summary = await _suite_summary(
                session,
                workspace_id=workspace_id,
                suite_run_id=previous.id,
                member_count=len(record.members),
            )
            delta = summary_delta(previous.id, summary, previous_summary)
        return PersistedIntentSuiteRun(
            run=run,
            suite=record.suite,
            child_runs=tuple(child_runs),
            child_run_ids=tuple(item.run.id for item in child_runs),
            summary=summary,
            delta=delta,
        )

    async def get_run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> PersistedIntentSuiteRun:
        row = (
            await session.execute(
                select(IntentSuiteRun, IntentSuite)
                .join(IntentSuite, IntentSuite.id == IntentSuiteRun.intent_suite_id)
                .where(
                    IntentSuiteRun.id == run_id,
                    IntentSuiteRun.workspace_id == workspace_id,
                    IntentSuite.workspace_id == workspace_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise IntentSuiteNotFoundError("Intent suite run not found")
        run, suite = row
        member_count = int(
            (
                await session.scalar(
                    select(func.count()).select_from(IntentSuiteMember).where(
                        IntentSuiteMember.workspace_id == workspace_id,
                        IntentSuiteMember.intent_suite_id == suite.id,
                    )
                )
            )
            or 0
        )
        summary = await _suite_summary(
            session,
            workspace_id=workspace_id,
            suite_run_id=run.id,
            member_count=member_count,
        )
        delta = None
        if run.previous_run_id is not None:
            previous_summary = await _suite_summary(
                session,
                workspace_id=workspace_id,
                suite_run_id=run.previous_run_id,
                member_count=member_count,
            )
            delta = summary_delta(run.previous_run_id, summary, previous_summary)
        child_run_ids = tuple(
            (
                await session.scalars(
                    select(IntentRun.id)
                    .join(
                        IntentSuiteMember,
                        IntentSuiteMember.buyer_intent_id == IntentRun.buyer_intent_id,
                    )
                    .where(
                        IntentRun.workspace_id == workspace_id,
                        IntentRun.intent_suite_run_id == run.id,
                        IntentSuiteMember.workspace_id == workspace_id,
                        IntentSuiteMember.intent_suite_id == suite.id,
                    )
                    .order_by(IntentSuiteMember.position, IntentRun.id)
                )
            ).all()
        )
        return PersistedIntentSuiteRun(
            run=run,
            suite=suite,
            child_runs=(),
            child_run_ids=child_run_ids,
            summary=summary,
            delta=delta,
        )


async def _suite_summary(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
    member_count: int,
) -> IntentSuiteRunSummary:
    rows = (
        await session.execute(
            select(IntentProductMatch.status, func.count())
            .join(IntentRun, IntentRun.id == IntentProductMatch.intent_run_id)
            .where(
                IntentProductMatch.workspace_id == workspace_id,
                IntentRun.workspace_id == workspace_id,
                IntentRun.intent_suite_run_id == suite_run_id,
            )
            .group_by(IntentProductMatch.status)
        )
    ).all()
    counts = defaultdict(int, {str(status): int(count) for status, count in rows})
    target_count = sum(counts.values())
    product_count = int(
        (
            await session.scalar(
                select(func.count(func.distinct(IntentProductMatch.product_id)))
                .select_from(IntentProductMatch)
                .join(IntentRun, IntentRun.id == IntentProductMatch.intent_run_id)
                .where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.intent_suite_run_id == suite_run_id,
                )
            )
        )
        or 0
    )
    intent_run_count = int(
        (
            await session.scalar(
                select(func.count()).select_from(IntentRun).where(
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.intent_suite_run_id == suite_run_id,
                )
            )
        )
        or 0
    )
    return IntentSuiteRunSummary(
        member_count=member_count,
        intent_run_count=intent_run_count,
        target_count=target_count,
        product_count=product_count,
        confident_match_count=counts["confident_match"],
        possible_match_missing_data_count=counts["possible_match_missing_data"],
        non_match_count=counts["non_match"],
        insufficient_category_data_count=counts["insufficient_category_data"],
        confident_coverage_basis_points=coverage_basis_points(
            counts["confident_match"],
            target_count,
        ),
    )


def coverage_basis_points(confident_match_count: int, target_count: int) -> int:
    if target_count <= 0:
        return 0
    return confident_match_count * 10_000 // target_count


def summary_delta(
    previous_run_id: uuid.UUID,
    current: IntentSuiteRunSummary,
    previous: IntentSuiteRunSummary,
) -> IntentSuiteRunDelta:
    return IntentSuiteRunDelta(
        previous_run_id=previous_run_id,
        target_count_delta=current.target_count - previous.target_count,
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


def suite_snapshot_hash(
    record: IntentSuiteRecord,
    *,
    product_ids: tuple[uuid.UUID, ...],
    child_runs: tuple[PersistedIntentRun, ...],
) -> str:
    if len(record.members) != len(child_runs):
        raise IntentSuiteMemberError("Suite snapshot requires one child run per member")
    payload = {
        "suite_id": str(record.suite.id),
        "members": [
            {
                "position": item.member.position,
                "buyer_intent_id": str(item.intent.id),
                "lineage_id": str(item.intent.lineage_id),
                "version": item.intent.version,
                "child_snapshot_hash": child.run.source_snapshot_hash,
            }
            for item, child in zip(record.members, child_runs, strict=True)
        ],
        "product_ids": [str(item) for item in sorted(product_ids)],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
