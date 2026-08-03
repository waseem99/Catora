from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.audit import AuditFinding, AuditRun
from catora_api.db.models.authority import (
    AuthorityObservationRecord,
    AuthorityOpportunityRecord,
    AuthorityProviderAccount,
)
from catora_api.db.models.git_publishing import GitChangeProposal, GitRepositoryConnection
from catora_api.db.models.local_profiles import (
    BranchLocalProfileLink,
    LocalProfileConflictRecord,
    LocalProfileObservationRecord,
    LocalProfileProviderAccount,
)
from catora_api.db.models.measurement import (
    MeasurementObservationRecord,
    MeasurementProviderAccount,
)
from catora_api.db.models.reputation import (
    ReviewAnalysisRecord,
    ReviewObservationRecord,
    ReviewProviderAccount,
    ReviewResponseDraftRecord,
)
from catora_api.db.models.restaurant import RestaurantFactObservation
from catora_api.db.models.restaurant_answers import RestaurantAnswerResult, RestaurantAnswerRun
from catora_api.operations_console.models import ConsoleMetric, ConsoleSection

_METRIC_VERSION = "restaurant-operations-metric/v1"


async def reconcile_persisted_sections(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generated_at: datetime | None = None,
    brand_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> tuple[ConsoleSection, ...]:
    instant = generated_at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return (
        await _catalog_section(
            session,
            workspace_id=workspace_id,
            instant=instant,
            brand_id=brand_id,
            location_id=location_id,
        ),
        await _technical_section(session, workspace_id=workspace_id, instant=instant),
        await _answer_section(session, workspace_id=workspace_id, instant=instant),
        await _local_profile_section(session, workspace_id=workspace_id, instant=instant),
        await _reputation_section(session, workspace_id=workspace_id, instant=instant),
        await _measurement_section(session, workspace_id=workspace_id, instant=instant),
        await _authority_section(session, workspace_id=workspace_id, instant=instant),
        await _publishing_section(session, workspace_id=workspace_id, instant=instant),
    )


async def _catalog_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
    brand_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
) -> ConsoleSection:
    statement = select(
        func.count(RestaurantFactObservation.id),
        func.max(RestaurantFactObservation.observed_at),
        func.count(RestaurantFactObservation.id).filter(
            RestaurantFactObservation.fact_state != "supported"
        ),
    ).where(RestaurantFactObservation.workspace_id == workspace_id)
    if location_id is not None:
        statement = statement.where(
            RestaurantFactObservation.entity_type == "location",
            RestaurantFactObservation.entity_id == location_id,
        )
    elif brand_id is not None:
        statement = statement.where(
            RestaurantFactObservation.entity_type == "brand",
            RestaurantFactObservation.entity_id == brand_id,
        )
    count, latest, non_supported = (await session.execute(statement)).one()
    total = int(count or 0)
    latest_at = cast(datetime | None, latest)
    if total == 0:
        return _unavailable(
            key="catalog_freshness",
            title="Catalog freshness",
            reason="No persisted restaurant fact observations exist for the selected scope.",
        )
    issue_count = int(non_supported or 0)
    state = "partial" if issue_count else "current"
    return ConsoleSection(
        key="catalog_freshness",
        state=state,
        title="Catalog freshness",
        summary="Restaurant facts are reconciled from immutable source observations.",
        metrics=(
            _metric("catalog.fact_count", "Persisted facts", total, "count", latest_at),
            _metric(
                "catalog.non_supported_count",
                "Partial, stale, conflicting or inaccessible facts",
                issue_count,
                "count",
                latest_at,
            ),
        ),
        evidence_references=("table:restaurant_fact_observations",),
        observed_at=latest_at,
        stale_after=_after(latest_at, days=7),
    )


async def _technical_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    run = await session.scalar(
        select(AuditRun)
        .where(AuditRun.workspace_id == workspace_id, AuditRun.status == "completed")
        .order_by(AuditRun.completed_at.desc(), AuditRun.id.desc())
        .limit(1)
    )
    if run is None or run.completed_at is None:
        return _unavailable(
            key="technical_seo",
            title="Technical and on-page audit",
            reason="No completed persisted audit run is available.",
        )
    finding_count = int(
        await session.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.workspace_id == workspace_id,
                AuditFinding.audit_run_id == run.id,
                AuditFinding.status.in_(("new", "ongoing", "regressed")),
            )
        )
        or 0
    )
    critical_count = int(
        await session.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.workspace_id == workspace_id,
                AuditFinding.audit_run_id == run.id,
                AuditFinding.severity == "critical",
                AuditFinding.status.in_(("new", "ongoing", "regressed")),
            )
        )
        or 0
    )
    state = "blocked" if critical_count else ("partial" if finding_count else "current")
    reason = "Critical persisted audit findings require human review." if state == "blocked" else None
    return ConsoleSection(
        key="technical_seo",
        state=state,
        title="Technical and on-page audit",
        summary="Latest completed workspace audit; entity coverage remains visible in the source run.",
        metrics=(
            _metric("technical.open_findings", "Open findings", finding_count, "count", run.completed_at),
            _metric("technical.critical_findings", "Critical findings", critical_count, "count", run.completed_at),
        ) if state != "blocked" else (),
        evidence_references=(f"audit_run:{run.id}",),
        observed_at=run.completed_at,
        stale_after=_after(run.completed_at, days=7),
        unavailable_reason=reason,
    )


async def _answer_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    run = await session.scalar(
        select(RestaurantAnswerRun)
        .where(RestaurantAnswerRun.workspace_id == workspace_id)
        .order_by(RestaurantAnswerRun.evaluated_at.desc(), RestaurantAnswerRun.id.desc())
        .limit(1)
    )
    if run is None:
        return _unavailable(
            key="answer_readiness",
            title="Answer readiness",
            reason="No persisted restaurant answer-evaluation run is available.",
        )
    result_count = int(
        await session.scalar(
            select(func.count(RestaurantAnswerResult.id)).where(
                RestaurantAnswerResult.workspace_id == workspace_id,
                RestaurantAnswerResult.run_id == run.id,
            )
        )
        or 0
    )
    unsupported = sum(
        int(run.state_counts.get(key, 0))
        for key in ("partial", "unsupported", "stale", "conflicting", "inaccessible")
    )
    state = "partial" if unsupported else "current"
    return ConsoleSection(
        key="answer_readiness",
        state=state,
        title="Answer readiness",
        summary="Question results are derived from persisted restaurant fact evidence.",
        metrics=(
            _metric("answers.result_count", "Evaluated questions", result_count, "count", run.evaluated_at),
            _metric("answers.non_supported_count", "Non-supported answers", unsupported, "count", run.evaluated_at),
        ),
        evidence_references=(f"restaurant_answer_run:{run.id}",),
        observed_at=run.evaluated_at,
        stale_after=_after(run.evaluated_at, days=7),
    )


async def _local_profile_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    accounts, disconnected = await _account_counts(
        session,
        model=LocalProfileProviderAccount,
        workspace_id=workspace_id,
    )
    if accounts == 0:
        return _unavailable(
            key="local_profiles",
            title="Local profiles",
            reason="No local-profile provider account is configured.",
        )
    if disconnected == accounts:
        return _unavailable(
            key="local_profiles",
            title="Local profiles",
            reason="All local-profile provider accounts are disconnected.",
            state="disconnected",
        )
    observations, latest = await _count_latest(
        session,
        model=LocalProfileObservationRecord,
        time_column=LocalProfileObservationRecord.observed_at,
        workspace_id=workspace_id,
        extra=(LocalProfileObservationRecord.is_current.is_(True),),
    )
    conflicts = int(
        await session.scalar(
            select(func.count(LocalProfileConflictRecord.id)).where(
                LocalProfileConflictRecord.workspace_id == workspace_id,
                LocalProfileConflictRecord.status == "open",
            )
        )
        or 0
    )
    ambiguous = int(
        await session.scalar(
            select(func.count(BranchLocalProfileLink.id)).where(
                BranchLocalProfileLink.workspace_id == workspace_id,
                BranchLocalProfileLink.match_state.in_(("ambiguous", "unmatched")),
            )
        )
        or 0
    )
    state = "partial" if observations == 0 or conflicts or ambiguous else "current"
    return ConsoleSection(
        key="local_profiles",
        state=state,
        title="Local profiles",
        summary="Current provider observations and deterministic branch-link decisions.",
        metrics=(
            _metric("local.current_profiles", "Current profile observations", observations, "count", latest),
            _metric("local.open_conflicts", "Open field conflicts", conflicts, "count", latest),
            _metric("local.ambiguous_links", "Ambiguous or unmatched links", ambiguous, "count", latest),
        ),
        evidence_references=("table:local_profile_observations", "table:local_profile_conflicts"),
        observed_at=latest,
        stale_after=_after(latest, days=7),
    )


async def _reputation_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    accounts, disconnected = await _account_counts(
        session,
        model=ReviewProviderAccount,
        workspace_id=workspace_id,
    )
    if accounts == 0:
        return _unavailable(
            key="reputation",
            title="Reputation",
            reason="No review provider account is configured.",
        )
    if disconnected == accounts:
        return _unavailable(
            key="reputation",
            title="Reputation",
            reason="All review provider accounts are disconnected.",
            state="disconnected",
        )
    reviews, latest = await _count_latest(
        session,
        model=ReviewObservationRecord,
        time_column=ReviewObservationRecord.observed_at,
        workspace_id=workspace_id,
        extra=(ReviewObservationRecord.is_current.is_(True),),
    )
    escalations = int(
        await session.scalar(
            select(func.count(ReviewAnalysisRecord.id)).where(
                ReviewAnalysisRecord.workspace_id == workspace_id,
                ReviewAnalysisRecord.risk_level.in_(("high", "critical")),
            )
        )
        or 0
    )
    pending_drafts = int(
        await session.scalar(
            select(func.count(ReviewResponseDraftRecord.id)).where(
                ReviewResponseDraftRecord.workspace_id == workspace_id,
                ReviewResponseDraftRecord.status == "draft",
            )
        )
        or 0
    )
    state = "blocked" if escalations else ("partial" if reviews == 0 or pending_drafts else "current")
    reason = "High-risk review analyses require human escalation." if state == "blocked" else None
    return ConsoleSection(
        key="reputation",
        state=state,
        title="Reputation",
        summary="Current review observations, safety escalations and draft-only response workflow.",
        metrics=(
            _metric("reputation.current_reviews", "Current reviews", reviews, "count", latest),
            _metric("reputation.pending_drafts", "Pending response drafts", pending_drafts, "count", latest),
        ) if state != "blocked" else (),
        evidence_references=("table:review_observations", "table:review_analyses"),
        observed_at=latest,
        stale_after=_after(latest, days=3),
        unavailable_reason=reason,
    )


async def _measurement_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    accounts, disconnected = await _account_counts(
        session,
        model=MeasurementProviderAccount,
        workspace_id=workspace_id,
    )
    if accounts == 0:
        return _unavailable(
            key="measurement",
            title="Measurement",
            reason="No measurement provider account is configured.",
        )
    if disconnected == accounts:
        return _unavailable(
            key="measurement",
            title="Measurement",
            reason="All measurement provider accounts are disconnected.",
            state="disconnected",
        )
    observations, latest = await _count_latest(
        session,
        model=MeasurementObservationRecord,
        time_column=MeasurementObservationRecord.observed_at,
        workspace_id=workspace_id,
    )
    degraded = int(
        await session.scalar(
            select(func.count(MeasurementObservationRecord.id)).where(
                MeasurementObservationRecord.workspace_id == workspace_id,
                MeasurementObservationRecord.freshness_state != "current",
            )
        )
        or 0
    )
    sampled = int(
        await session.scalar(
            select(func.count(MeasurementObservationRecord.id)).where(
                MeasurementObservationRecord.workspace_id == workspace_id,
                MeasurementObservationRecord.sample_state != "complete",
            )
        )
        or 0
    )
    state = "partial" if observations == 0 or degraded or sampled else "current"
    return ConsoleSection(
        key="measurement",
        state=state,
        title="Measurement",
        summary="Aggregate provider observations; comparisons remain correlation-only.",
        metrics=(
            _metric("measurement.observations", "Aggregate observations", observations, "count", latest),
            _metric("measurement.degraded", "Stale, disconnected or unavailable observations", degraded, "count", latest),
            _metric("measurement.sampled", "Sampled or partial observations", sampled, "count", latest),
        ),
        evidence_references=("table:measurement_observations",),
        observed_at=latest,
        stale_after=_after(latest, days=3),
    )


async def _authority_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    accounts, disconnected = await _account_counts(
        session,
        model=AuthorityProviderAccount,
        workspace_id=workspace_id,
    )
    if accounts == 0:
        return _unavailable(
            key="authority",
            title="Off-page authority",
            reason="No authority provider account is configured.",
        )
    if disconnected == accounts:
        return _unavailable(
            key="authority",
            title="Off-page authority",
            reason="All authority provider accounts are disconnected.",
            state="disconnected",
        )
    observations, latest = await _count_latest(
        session,
        model=AuthorityObservationRecord,
        time_column=AuthorityObservationRecord.observed_at,
        workspace_id=workspace_id,
    )
    opportunities = int(
        await session.scalar(
            select(func.count(AuthorityOpportunityRecord.id)).where(
                AuthorityOpportunityRecord.workspace_id == workspace_id,
                AuthorityOpportunityRecord.state == "open",
            )
        )
        or 0
    )
    suppressed = int(
        await session.scalar(
            select(func.count(AuthorityOpportunityRecord.id)).where(
                AuthorityOpportunityRecord.workspace_id == workspace_id,
                AuthorityOpportunityRecord.state == "suppressed",
            )
        )
        or 0
    )
    state = "partial" if observations == 0 or suppressed else "current"
    return ConsoleSection(
        key="authority",
        state=state,
        title="Off-page authority",
        summary="Evidence-backed opportunities only; outreach remains draft-only and non-sendable.",
        metrics=(
            _metric("authority.observations", "Authority observations", observations, "count", latest),
            _metric("authority.open_opportunities", "Open opportunities", opportunities, "count", latest),
            _metric("authority.suppressed", "Suppressed opportunities", suppressed, "count", latest),
        ),
        evidence_references=("table:authority_observations", "table:authority_opportunities"),
        observed_at=latest,
        stale_after=_after(latest, days=7),
    )


async def _publishing_section(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    instant: datetime,
) -> ConsoleSection:
    del instant
    accounts, disconnected = await _account_counts(
        session,
        model=GitRepositoryConnection,
        workspace_id=workspace_id,
    )
    if accounts == 0:
        return _unavailable(
            key="publishing",
            title="Governed publishing",
            reason="No governed repository connection is configured.",
        )
    if disconnected == accounts:
        return _unavailable(
            key="publishing",
            title="Governed publishing",
            reason="All governed repository connections are disconnected.",
            state="disconnected",
        )
    proposals, latest = await _count_latest(
        session,
        model=GitChangeProposal,
        time_column=GitChangeProposal.updated_at,
        workspace_id=workspace_id,
    )
    pending = int(
        await session.scalar(
            select(func.count(GitChangeProposal.id)).where(
                GitChangeProposal.workspace_id == workspace_id,
                GitChangeProposal.status.in_(("draft", "approved", "submitted")),
            )
        )
        or 0
    )
    state = "partial" if pending else "current"
    return ConsoleSection(
        key="publishing",
        state=state,
        title="Governed publishing",
        summary="Proposal branches and draft pull requests only; Catora cannot merge or deploy.",
        metrics=(
            _metric("publishing.proposals", "Change proposals", proposals, "count", latest),
            _metric("publishing.pending", "Pending proposals", pending, "count", latest),
        ),
        evidence_references=("table:git_change_proposals",),
        observed_at=latest,
        stale_after=_after(latest, days=30),
    )


async def _account_counts(
    session: AsyncSession,
    *,
    model: type[object],
    workspace_id: uuid.UUID,
) -> tuple[int, int]:
    workspace_column = getattr(model, "workspace_id")
    status_column = getattr(model, "status")
    identifier = getattr(model, "id")
    count, disconnected = (
        await session.execute(
            select(
                func.count(identifier),
                func.count(identifier).filter(status_column == "disconnected"),
            ).where(workspace_column == workspace_id)
        )
    ).one()
    return int(count or 0), int(disconnected or 0)


async def _count_latest(
    session: AsyncSession,
    *,
    model: type[object],
    time_column: object,
    workspace_id: uuid.UUID,
    extra: tuple[object, ...] = (),
) -> tuple[int, datetime | None]:
    workspace_column = getattr(model, "workspace_id")
    identifier = getattr(model, "id")
    statement = select(func.count(identifier), func.max(time_column)).where(
        workspace_column == workspace_id,
        *extra,
    )
    count, latest = (await session.execute(statement)).one()
    return int(count or 0), cast(datetime | None, latest)


def _metric(
    key: str,
    label: str,
    value: int | float | str | bool | None,
    unit: str,
    observed_at: datetime | None,
) -> ConsoleMetric:
    return ConsoleMetric(
        key=key,
        label=label,
        value=value,
        unit=unit,
        definition_version=_METRIC_VERSION,
        source_coverage="workspace-scoped persisted evidence only",
        observed_at=observed_at,
        source_references=(f"metric:{key}",),
    )


def _after(value: datetime | None, *, days: int) -> datetime | None:
    return value + timedelta(days=days) if value is not None else None


def _unavailable(
    *,
    key: str,
    title: str,
    reason: str,
    state: str = "unavailable",
) -> ConsoleSection:
    return ConsoleSection(
        key=key,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        title=title,
        summary=reason,
        unavailable_reason=reason,
        evidence_references=(f"section:{key}",),
    )
