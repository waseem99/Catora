from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import (
    IntentProductMatch,
    IntentRun,
    IntentSuite,
    IntentSuiteMember,
    IntentSuiteRun,
)
from catora_api.intents.suites import (
    IntentSuiteNotFoundError,
    IntentSuiteRunSummary,
    coverage_basis_points,
)

_MATCH_STATUSES = {
    "confident_match",
    "possible_match_missing_data",
    "non_match",
    "insufficient_category_data",
}


class IntentSuiteRunHistoryDataError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IntentSuiteRunHistoryRecord:
    run: IntentSuiteRun
    requested_product_ids: tuple[uuid.UUID, ...]
    summary: IntentSuiteRunSummary


@dataclass(frozen=True, slots=True)
class IntentSuiteRunHistoryPage:
    items: tuple[IntentSuiteRunHistoryRecord, ...]
    total: int


class IntentSuiteRunHistoryService:
    async def list(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        suite_id: uuid.UUID,
        status: str | None,
        offset: int,
        limit: int,
    ) -> IntentSuiteRunHistoryPage:
        suite_exists = await session.scalar(
            select(IntentSuite.id).where(
                IntentSuite.id == suite_id,
                IntentSuite.workspace_id == workspace_id,
            )
        )
        if suite_exists is None:
            raise IntentSuiteNotFoundError("Intent suite not found")

        query = select(IntentSuiteRun).where(
            IntentSuiteRun.workspace_id == workspace_id,
            IntentSuiteRun.intent_suite_id == suite_id,
        )
        if status is not None:
            query = query.where(IntentSuiteRun.status == status)
        total = int(
            (
                await session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
            )
            or 0
        )
        runs = tuple(
            (
                await session.scalars(
                    query.order_by(
                        IntentSuiteRun.created_at.desc(),
                        IntentSuiteRun.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        if not runs:
            return IntentSuiteRunHistoryPage(items=(), total=total)

        member_count = int(
            (
                await session.scalar(
                    select(func.count()).select_from(IntentSuiteMember).where(
                        IntentSuiteMember.workspace_id == workspace_id,
                        IntentSuiteMember.intent_suite_id == suite_id,
                    )
                )
            )
            or 0
        )
        run_ids = tuple(run.id for run in runs)
        summaries = await suite_run_summaries(
            session,
            workspace_id=workspace_id,
            run_ids=run_ids,
            member_count=member_count,
        )
        records = tuple(
            IntentSuiteRunHistoryRecord(
                run=run,
                requested_product_ids=validated_requested_product_ids(run),
                summary=summaries[run.id],
            )
            for run in runs
        )
        return IntentSuiteRunHistoryPage(items=records, total=total)


async def suite_run_summaries(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    run_ids: tuple[uuid.UUID, ...],
    member_count: int,
) -> dict[uuid.UUID, IntentSuiteRunSummary]:
    if not run_ids:
        return {}

    raw_status_rows = (
        await session.execute(
            select(
                IntentRun.intent_suite_run_id,
                IntentProductMatch.status,
                func.count(),
            )
            .select_from(IntentProductMatch)
            .join(IntentRun, IntentRun.id == IntentProductMatch.intent_run_id)
            .where(
                IntentProductMatch.workspace_id == workspace_id,
                IntentRun.workspace_id == workspace_id,
                IntentRun.intent_suite_run_id.in_(run_ids),
            )
            .group_by(IntentRun.intent_suite_run_id, IntentProductMatch.status)
        )
    ).all()
    status_rows = tuple(
        (cast(uuid.UUID, run_id), str(match_status), int(count))
        for run_id, match_status, count in raw_status_rows
    )

    raw_product_rows = (
        await session.execute(
            select(
                IntentRun.intent_suite_run_id,
                func.count(func.distinct(IntentProductMatch.product_id)),
            )
            .select_from(IntentProductMatch)
            .join(IntentRun, IntentRun.id == IntentProductMatch.intent_run_id)
            .where(
                IntentProductMatch.workspace_id == workspace_id,
                IntentRun.workspace_id == workspace_id,
                IntentRun.intent_suite_run_id.in_(run_ids),
            )
            .group_by(IntentRun.intent_suite_run_id)
        )
    ).all()
    product_rows = tuple(
        (cast(uuid.UUID, run_id), int(count)) for run_id, count in raw_product_rows
    )

    raw_child_rows = (
        await session.execute(
            select(IntentRun.intent_suite_run_id, func.count())
            .where(
                IntentRun.workspace_id == workspace_id,
                IntentRun.intent_suite_run_id.in_(run_ids),
            )
            .group_by(IntentRun.intent_suite_run_id)
        )
    ).all()
    child_rows = tuple(
        (cast(uuid.UUID, run_id), int(count)) for run_id, count in raw_child_rows
    )
    return build_suite_run_summaries(
        run_ids,
        member_count=member_count,
        status_rows=status_rows,
        product_rows=product_rows,
        child_rows=child_rows,
    )


def build_suite_run_summaries(
    run_ids: tuple[uuid.UUID, ...],
    *,
    member_count: int,
    status_rows: tuple[tuple[uuid.UUID, str, int], ...],
    product_rows: tuple[tuple[uuid.UUID, int], ...],
    child_rows: tuple[tuple[uuid.UUID, int], ...],
) -> dict[uuid.UUID, IntentSuiteRunSummary]:
    if len(run_ids) != len(set(run_ids)):
        raise IntentSuiteRunHistoryDataError("Suite run identifiers must be unique")
    if member_count < 0:
        raise IntentSuiteRunHistoryDataError("Suite member count cannot be negative")
    known = set(run_ids)
    status_counts: dict[uuid.UUID, defaultdict[str, int]] = {
        run_id: defaultdict(int) for run_id in run_ids
    }
    seen_statuses: set[tuple[uuid.UUID, str]] = set()
    for run_id, match_status, count in status_rows:
        if run_id not in known:
            raise IntentSuiteRunHistoryDataError("Status row references an unknown suite run")
        if match_status not in _MATCH_STATUSES:
            raise IntentSuiteRunHistoryDataError("Status row contains an unknown match state")
        if count < 0:
            raise IntentSuiteRunHistoryDataError("Status count cannot be negative")
        key = (run_id, match_status)
        if key in seen_statuses:
            raise IntentSuiteRunHistoryDataError("Duplicate status aggregate row")
        seen_statuses.add(key)
        status_counts[run_id][match_status] = count

    product_counts = _count_rows("product", known, product_rows)
    child_counts = _count_rows("child run", known, child_rows)
    summaries: dict[uuid.UUID, IntentSuiteRunSummary] = {}
    for run_id in run_ids:
        counts = status_counts[run_id]
        target_count = sum(counts.values())
        summaries[run_id] = IntentSuiteRunSummary(
            member_count=member_count,
            intent_run_count=child_counts.get(run_id, 0),
            target_count=target_count,
            product_count=product_counts.get(run_id, 0),
            confident_match_count=counts["confident_match"],
            possible_match_missing_data_count=counts[
                "possible_match_missing_data"
            ],
            non_match_count=counts["non_match"],
            insufficient_category_data_count=counts[
                "insufficient_category_data"
            ],
            confident_coverage_basis_points=coverage_basis_points(
                counts["confident_match"],
                target_count,
            ),
        )
    return summaries


def _count_rows(
    label: str,
    known_run_ids: set[uuid.UUID],
    rows: tuple[tuple[uuid.UUID, int], ...],
) -> dict[uuid.UUID, int]:
    result: dict[uuid.UUID, int] = {}
    for run_id, count in rows:
        if run_id not in known_run_ids:
            raise IntentSuiteRunHistoryDataError(
                f"{label.title()} row references an unknown suite run"
            )
        if run_id in result:
            raise IntentSuiteRunHistoryDataError(f"Duplicate {label} aggregate row")
        if count < 0:
            raise IntentSuiteRunHistoryDataError(f"{label.title()} count cannot be negative")
        result[run_id] = count
    return result


def validated_requested_product_ids(run: IntentSuiteRun) -> tuple[uuid.UUID, ...]:
    raw = run.requested_product_ids
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise IntentSuiteRunHistoryDataError(
            "Stored suite-run product selection is invalid"
        )
    try:
        product_ids = tuple(uuid.UUID(item) for item in raw)
    except ValueError as exc:
        raise IntentSuiteRunHistoryDataError(
            "Stored suite-run product selection is invalid"
        ) from exc
    if len(product_ids) != len(set(product_ids)):
        raise IntentSuiteRunHistoryDataError(
            "Stored suite-run product selection contains duplicates"
        )
    if product_ids != tuple(sorted(product_ids)):
        raise IntentSuiteRunHistoryDataError(
            "Stored suite-run product selection is not canonical"
        )
    return product_ids
