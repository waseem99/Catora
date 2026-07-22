from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import (
    IntentProductMatch,
    IntentRun,
    IntentSuiteMember,
    IntentSuiteRun,
)
from catora_api.intents.coverage import (
    IntentCoverageDataError,
    IntentCoverageNotFoundError,
    IntentCoverageStateError,
    persisted_match_snapshot,
)
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    _validated_source,
)
from catora_api.intents.types import IntentMatchResult, IntentMatchStatus

TransitionPresence = Literal["retained", "added", "removed"]
_CHILD_SNAPSHOT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SCORE_SCALE = Decimal(10_000)


@dataclass(frozen=True, slots=True)
class IntentMatchEvidence:
    match_id: uuid.UUID
    intent_run_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    status: IntentMatchStatus
    soft_score_basis_points: int
    explanation: IntentMatchResult
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IntentMatchTransition:
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    presence: TransitionPresence
    selected: IntentMatchEvidence | None
    baseline: IntentMatchEvidence | None
    status_changed: bool
    soft_score_basis_points_delta: int | None
    evidence_changed: bool

    @property
    def changed(self) -> bool:
        return (
            self.presence != "retained"
            or self.status_changed
            or self.soft_score_basis_points_delta not in {None, 0}
            or self.evidence_changed
        )


@dataclass(frozen=True, slots=True)
class IntentMatchTransitionPage:
    selected_suite_run: IntentSuiteRun
    baseline_suite_run: IntentSuiteRun
    member: IntentSuiteMember
    selected_intent_run: IntentRun
    baseline_intent_run: IntentRun
    selection_changed: bool
    items: tuple[IntentMatchTransition, ...]
    total: int


class IntentMatchTransitionService:
    async def compare(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        selected_suite_run_id: uuid.UUID,
        baseline_suite_run_id: uuid.UUID,
        buyer_intent_id: uuid.UUID,
        selected_status: IntentMatchStatus | None,
        baseline_status: IntentMatchStatus | None,
        changed_only: bool,
        offset: int,
        limit: int,
    ) -> IntentMatchTransitionPage:
        if selected_suite_run_id == baseline_suite_run_id:
            raise IntentCoverageDataError(
                "An intent suite run cannot be compared with itself"
            )
        selected_suite_run = await _suite_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_suite_run_id,
        )
        baseline_suite_run = await _suite_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_suite_run_id,
        )
        if selected_suite_run.intent_suite_id != baseline_suite_run.intent_suite_id:
            raise IntentCoverageDataError(
                "Intent suite runs belong to different suites"
            )
        selected_products = _validated_products(selected_suite_run, label="Selected")
        baseline_products = _validated_products(baseline_suite_run, label="Baseline")
        member = await _suite_member(
            session,
            workspace_id=workspace_id,
            suite_id=selected_suite_run.intent_suite_id,
            buyer_intent_id=buyer_intent_id,
        )
        selected_intent_run = await _child_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=selected_suite_run.id,
            buyer_intent_id=buyer_intent_id,
            label="Selected",
        )
        baseline_intent_run = await _child_run(
            session,
            workspace_id=workspace_id,
            suite_run_id=baseline_suite_run.id,
            buyer_intent_id=buyer_intent_id,
            label="Baseline",
        )
        selected_matches = await _matches(
            session,
            workspace_id=workspace_id,
            intent_run=selected_intent_run,
        )
        baseline_matches = await _matches(
            session,
            workspace_id=workspace_id,
            intent_run=baseline_intent_run,
        )
        items, total = build_match_transitions(
            selected_matches,
            baseline_matches,
            selected_status=selected_status,
            baseline_status=baseline_status,
            changed_only=changed_only,
            offset=offset,
            limit=limit,
        )
        return IntentMatchTransitionPage(
            selected_suite_run=selected_suite_run,
            baseline_suite_run=baseline_suite_run,
            member=member,
            selected_intent_run=selected_intent_run,
            baseline_intent_run=baseline_intent_run,
            selection_changed=selected_products != baseline_products,
            items=items,
            total=total,
        )


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
    return run


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


async def _suite_member(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    buyer_intent_id: uuid.UUID,
) -> IntentSuiteMember:
    member = await session.scalar(
        select(IntentSuiteMember).where(
            IntentSuiteMember.workspace_id == workspace_id,
            IntentSuiteMember.intent_suite_id == suite_id,
            IntentSuiteMember.buyer_intent_id == buyer_intent_id,
        )
    )
    if member is None:
        raise IntentCoverageNotFoundError("Buyer intent is not a member of the suite")
    if member.position < 0:
        raise IntentCoverageDataError("Intent suite member position is invalid")
    return member


async def _child_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    suite_run_id: uuid.UUID,
    buyer_intent_id: uuid.UUID,
    label: str,
) -> IntentRun:
    runs = tuple(
        (
            await session.scalars(
                select(IntentRun).where(
                    IntentRun.workspace_id == workspace_id,
                    IntentRun.intent_suite_run_id == suite_run_id,
                    IntentRun.buyer_intent_id == buyer_intent_id,
                )
            )
        ).all()
    )
    if not runs:
        raise IntentCoverageDataError(
            f"{label} suite run has no child run for the buyer intent"
        )
    if len(runs) != 1:
        raise IntentCoverageDataError(
            f"{label} suite run has duplicate child runs for the buyer intent"
        )
    run = runs[0]
    if run.status != "completed":
        raise IntentCoverageDataError(f"{label} child intent run is not completed")
    if run.started_at is None or run.completed_at is None:
        raise IntentCoverageDataError(
            f"{label} child intent run timestamps are incomplete"
        )
    if _CHILD_SNAPSHOT_PATTERN.fullmatch(run.source_snapshot_hash) is None:
        raise IntentCoverageDataError(
            f"{label} child intent run snapshot is invalid"
        )
    return run


async def _matches(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    intent_run: IntentRun,
) -> tuple[IntentMatchEvidence, ...]:
    rows = tuple(
        (
            await session.scalars(
                select(IntentProductMatch)
                .where(
                    IntentProductMatch.workspace_id == workspace_id,
                    IntentProductMatch.intent_run_id == intent_run.id,
                )
                .order_by(
                    IntentProductMatch.product_id,
                    IntentProductMatch.variant_id.asc().nulls_first(),
                    IntentProductMatch.id,
                )
            )
        ).all()
    )
    evidence = tuple(
        _match_evidence(match, buyer_intent_id=intent_run.buyer_intent_id)
        for match in rows
    )
    _match_map(evidence, label="Persisted")
    return evidence


def _match_evidence(
    match: IntentProductMatch,
    *,
    buyer_intent_id: uuid.UUID,
) -> IntentMatchEvidence:
    snapshot = persisted_match_snapshot(match, buyer_intent_id)
    score = Decimal(match.score or 0)
    score_basis_points = int(score * _SCORE_SCALE)
    if score < 0 or score > 1 or Decimal(score_basis_points) / _SCORE_SCALE != score:
        raise IntentCoverageDataError("Stored intent match score is invalid")
    if score_basis_points != snapshot.result.soft_score_basis_points:
        raise IntentCoverageDataError(
            "Stored intent match score does not reconcile with its explanation"
        )
    return IntentMatchEvidence(
        match_id=snapshot.match_id,
        intent_run_id=snapshot.intent_run_id,
        product_id=snapshot.product_id,
        variant_id=snapshot.variant_id,
        status=snapshot.result.status,
        soft_score_basis_points=score_basis_points,
        explanation=snapshot.result,
        created_at=match.created_at,
    )


def build_match_transitions(
    selected: tuple[IntentMatchEvidence, ...],
    baseline: tuple[IntentMatchEvidence, ...],
    *,
    selected_status: IntentMatchStatus | None,
    baseline_status: IntentMatchStatus | None,
    changed_only: bool,
    offset: int,
    limit: int,
) -> tuple[tuple[IntentMatchTransition, ...], int]:
    selected_by_target = _match_map(selected, label="Selected")
    baseline_by_target = _match_map(baseline, label="Baseline")
    keys = sorted(
        set(selected_by_target) | set(baseline_by_target),
        key=lambda value: (
            value[0],
            value[1] is not None,
            value[1] or uuid.UUID(int=0),
        ),
    )
    filtered: list[IntentMatchTransition] = []
    for product_id, variant_id in keys:
        selected_item = selected_by_target.get((product_id, variant_id))
        baseline_item = baseline_by_target.get((product_id, variant_id))
        if selected_status is not None and (
            selected_item is None or selected_item.status != selected_status
        ):
            continue
        if baseline_status is not None and (
            baseline_item is None or baseline_item.status != baseline_status
        ):
            continue
        transition = _transition(
            product_id,
            variant_id,
            selected=selected_item,
            baseline=baseline_item,
        )
        if changed_only and not transition.changed:
            continue
        filtered.append(transition)
    total = len(filtered)
    return tuple(filtered[offset : offset + limit]), total


def _match_map(
    items: tuple[IntentMatchEvidence, ...],
    *,
    label: str,
) -> dict[tuple[uuid.UUID, uuid.UUID | None], IntentMatchEvidence]:
    by_target: dict[tuple[uuid.UUID, uuid.UUID | None], IntentMatchEvidence] = {}
    match_ids: set[uuid.UUID] = set()
    for item in items:
        key = (item.product_id, item.variant_id)
        if key in by_target:
            raise IntentCoverageDataError(
                f"{label} intent matches contain duplicate targets"
            )
        if item.match_id in match_ids:
            raise IntentCoverageDataError(
                f"{label} intent matches contain duplicate row identities"
            )
        if item.explanation.product_id != item.product_id:
            raise IntentCoverageDataError(
                f"{label} intent match product identity does not reconcile"
            )
        if item.explanation.variant_id != item.variant_id:
            raise IntentCoverageDataError(
                f"{label} intent match variant identity does not reconcile"
            )
        if item.explanation.status != item.status:
            raise IntentCoverageDataError(
                f"{label} intent match status does not reconcile"
            )
        if item.explanation.soft_score_basis_points != item.soft_score_basis_points:
            raise IntentCoverageDataError(
                f"{label} intent match score does not reconcile"
            )
        by_target[key] = item
        match_ids.add(item.match_id)
    return by_target


def _transition(
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    *,
    selected: IntentMatchEvidence | None,
    baseline: IntentMatchEvidence | None,
) -> IntentMatchTransition:
    if selected is not None and baseline is not None:
        presence: TransitionPresence = "retained"
        status_changed = selected.status != baseline.status
        score_delta = (
            selected.soft_score_basis_points - baseline.soft_score_basis_points
        )
        evidence_changed = _evidence_payload(
            selected.explanation
        ) != _evidence_payload(baseline.explanation)
    elif selected is not None:
        presence = "added"
        status_changed = False
        score_delta = None
        evidence_changed = True
    elif baseline is not None:
        presence = "removed"
        status_changed = False
        score_delta = None
        evidence_changed = True
    else:
        raise IntentCoverageDataError("Intent match transition has no evidence")
    return IntentMatchTransition(
        product_id=product_id,
        variant_id=variant_id,
        presence=presence,
        selected=selected,
        baseline=baseline,
        status_changed=status_changed,
        soft_score_basis_points_delta=score_delta,
        evidence_changed=evidence_changed,
    )


def _evidence_payload(result: IntentMatchResult) -> dict[str, object]:
    payload: dict[str, object] = result.model_dump(mode="json")
    for field in (
        "product_id",
        "variant_id",
        "status",
        "soft_score_basis_points",
    ):
        payload.pop(field, None)
    return payload
