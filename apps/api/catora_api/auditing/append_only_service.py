from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing.lifecycle import next_finding_status
from catora_api.auditing.service import AuditConfigurationError, _database_value
from catora_api.auditing.stateful_service import StatefulAuditRunService
from catora_api.auditing.types import FindingCandidate
from catora_api.db.models.audit import AuditFinding, AuditRun, RuleVersion


class AppendOnlyAuditRunService(StatefulAuditRunService):
    async def _reconcile_findings(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        findings: Mapping[str, FindingCandidate],
    ) -> tuple[list[str], int]:
        previous_findings = await _run_findings(session, run)
        latest_history = await _latest_history(session, run=run, findings=findings)
        category_keys = await _category_keys(session, findings)
        now = datetime.now(UTC)
        statuses: list[str] = []
        resolved_count = 0

        for previous in previous_findings:
            if previous.status == "resolved":
                continue
            if previous.fingerprint not in findings:
                session.add(
                    _copy_finding(
                        previous,
                        run=run,
                        status="resolved",
                        last_seen_at=now,
                        resolved_at=now,
                    )
                )
                resolved_count += 1

        for fingerprint, candidate in sorted(findings.items()):
            historical = latest_history.get(fingerprint)
            status = next_finding_status(
                historical.status if historical is not None else None
            )
            statuses.append(status)
            session.add(
                _finding_from_candidate(
                    candidate,
                    category_key=category_keys[candidate.rule_version_id],
                    run=run,
                    historical=historical,
                    status=status,
                    now=now,
                )
            )
        await session.flush()
        return statuses, resolved_count

    async def _reconcile_incremental_findings(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        findings: Mapping[str, FindingCandidate],
        target_product_ids: set[uuid.UUID],
    ) -> tuple[list[str], int]:
        previous_findings = await _run_findings(session, run)
        latest_history = await _latest_history(session, run=run, findings=findings)
        category_keys = await _category_keys(session, findings)
        now = datetime.now(UTC)
        statuses: list[str] = []
        resolved_count = 0

        for previous in previous_findings:
            if previous.status == "resolved":
                continue
            if previous.product_id not in target_product_ids:
                status = next_finding_status(previous.status)
                statuses.append(status)
                session.add(
                    _copy_finding(
                        previous,
                        run=run,
                        status=status,
                        last_seen_at=now,
                        resolved_at=None,
                    )
                )
            elif previous.fingerprint not in findings:
                session.add(
                    _copy_finding(
                        previous,
                        run=run,
                        status="resolved",
                        last_seen_at=now,
                        resolved_at=now,
                    )
                )
                resolved_count += 1

        for fingerprint, candidate in sorted(findings.items()):
            historical = latest_history.get(fingerprint)
            status = next_finding_status(
                historical.status if historical is not None else None
            )
            statuses.append(status)
            session.add(
                _finding_from_candidate(
                    candidate,
                    category_key=category_keys[candidate.rule_version_id],
                    run=run,
                    historical=historical,
                    status=status,
                    now=now,
                )
            )
        await session.flush()
        return statuses, resolved_count


async def _run_findings(
    session: AsyncSession,
    run: AuditRun,
) -> list[AuditFinding]:
    if run.previous_run_id is None:
        return []
    return list(
        (
            await session.scalars(
                select(AuditFinding).where(
                    AuditFinding.workspace_id == run.workspace_id,
                    AuditFinding.audit_run_id == run.previous_run_id,
                )
            )
        ).all()
    )


async def _latest_history(
    session: AsyncSession,
    *,
    run: AuditRun,
    findings: Mapping[str, FindingCandidate],
) -> dict[str, AuditFinding]:
    if not findings:
        return {}
    historical_findings = (
        await session.scalars(
            select(AuditFinding)
            .join(AuditRun, AuditRun.id == AuditFinding.audit_run_id)
            .where(
                AuditFinding.workspace_id == run.workspace_id,
                AuditFinding.fingerprint.in_(sorted(findings)),
                AuditRun.status == "completed",
                AuditRun.id != run.id,
            )
            .order_by(
                AuditFinding.fingerprint,
                AuditFinding.last_seen_at.desc(),
                AuditFinding.id.desc(),
            )
        )
    ).all()
    latest: dict[str, AuditFinding] = {}
    for historical in historical_findings:
        latest.setdefault(historical.fingerprint, historical)
    return latest


async def _category_keys(
    session: AsyncSession,
    findings: Mapping[str, FindingCandidate],
) -> dict[uuid.UUID, str]:
    rule_version_ids = sorted(
        {candidate.rule_version_id for candidate in findings.values()},
        key=str,
    )
    if not rule_version_ids:
        return {}
    rows = (
        await session.execute(
            select(RuleVersion.id, RuleVersion.specification).where(
                RuleVersion.id.in_(rule_version_ids),
                RuleVersion.is_immutable.is_(True),
            )
        )
    ).all()
    category_keys: dict[uuid.UUID, str] = {}
    for rule_version_id, specification in rows:
        category_key = specification.get("category_key")
        if not isinstance(category_key, str) or not category_key:
            raise AuditConfigurationError(
                f"Rule version {rule_version_id} has no immutable category key"
            )
        category_keys[rule_version_id] = category_key
    missing = set(rule_version_ids) - set(category_keys)
    if missing:
        raise AuditConfigurationError(
            "Audit finding rule versions are missing category snapshots: "
            + ", ".join(sorted(str(item) for item in missing))
        )
    return category_keys


def _finding_from_candidate(
    candidate: FindingCandidate,
    *,
    category_key: str,
    run: AuditRun,
    historical: AuditFinding | None,
    status: str,
    now: datetime,
) -> AuditFinding:
    return AuditFinding(
        workspace_id=run.workspace_id,
        audit_run_id=run.id,
        previous_finding_id=historical.id if historical is not None else None,
        rule_version_id=candidate.rule_version_id,
        product_id=candidate.product_id,
        variant_id=candidate.variant_id,
        severity=candidate.severity,
        title=candidate.title,
        explanation=candidate.explanation,
        fingerprint=candidate.fingerprint,
        status=status,
        category_key=category_key,
        field_key=candidate.field_key,
        affected_value=_database_value(candidate.affected_value),
        business_impact=candidate.business_impact,
        remediation_type=candidate.remediation_type,
        failure_codes=list(candidate.failure_codes),
        evidence=[
            {
                "source_record_id": str(item.source_record_id),
                "field_path": item.field_path,
                "excerpt": item.excerpt,
                "checksum": item.checksum,
            }
            for item in candidate.evidence
        ],
        first_seen_at=historical.first_seen_at if historical is not None else now,
        last_seen_at=now,
        resolved_at=None,
    )


def _copy_finding(
    finding: AuditFinding,
    *,
    run: AuditRun,
    status: str,
    last_seen_at: datetime,
    resolved_at: datetime | None,
) -> AuditFinding:
    return AuditFinding(
        workspace_id=run.workspace_id,
        audit_run_id=run.id,
        previous_finding_id=finding.id,
        rule_version_id=finding.rule_version_id,
        product_id=finding.product_id,
        variant_id=finding.variant_id,
        severity=finding.severity,
        title=finding.title,
        explanation=finding.explanation,
        fingerprint=finding.fingerprint,
        status=status,
        category_key=finding.category_key,
        field_key=finding.field_key,
        affected_value=finding.affected_value,
        business_impact=finding.business_impact,
        remediation_type=finding.remediation_type,
        failure_codes=list(finding.failure_codes),
        evidence=list(finding.evidence),
        first_seen_at=finding.first_seen_at,
        last_seen_at=last_seen_at,
        resolved_at=resolved_at,
    )
