from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing.incremental import (
    catalog_snapshot_hash,
    merge_product_snapshot_hashes,
    merge_score_contributions,
    score_contributions_from_summary,
)
from catora_api.auditing.lifecycle import finding_count_summary, next_finding_status
from catora_api.auditing.rules import evaluate_product
from catora_api.auditing.scoring import (
    calculate_health_from_contributions,
    calculate_health_score,
)
from catora_api.auditing.service import (
    ACTIVE_AUDIT_STATUSES,
    AUDIT_BATCH_SIZE,
    AuditConfigurationError,
    AuditRunConflictError,
    AuditRunNotFoundError,
    AuditRunService,
    ProductHeader,
    _database_value,
    _score_payload,
    _snapshot_bytes,
)
from catora_api.auditing.types import FindingCandidate, RuleEvaluation
from catora_api.db.models.audit import AuditFinding, AuditRun, RuleDefinition, RuleVersion
from catora_api.db.models.catalog import (
    EvidenceReference,
    Product,
    ProductAttribute,
    ProductVariant,
)


class StatefulAuditRunService(AuditRunService):
    async def create_run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        taxonomy_version: str,
        mode: str,
    ) -> AuditRun:
        if mode == "full":
            run = await super().create_run(
                session,
                workspace_id=workspace_id,
                requested_by_user_id=requested_by_user_id,
                taxonomy_version=taxonomy_version,
                mode="full",
            )
            run.product_snapshot_hashes = {}
            return run
        if mode != "incremental":
            raise AuditConfigurationError(f"Unsupported audit mode {mode!r}")

        active_run_id = await session.scalar(
            select(AuditRun.id).where(
                AuditRun.workspace_id == workspace_id,
                AuditRun.status.in_(ACTIVE_AUDIT_STATUSES),
            )
        )
        if active_run_id is not None:
            raise AuditRunConflictError("An audit run is already active for this workspace")

        rule_version_ids = (
            await session.scalars(
                select(RuleVersion.id)
                .join(
                    RuleDefinition,
                    RuleDefinition.id == RuleVersion.rule_definition_id,
                )
                .where(
                    RuleVersion.workspace_id == workspace_id,
                    RuleVersion.version == taxonomy_version,
                    RuleVersion.is_immutable.is_(True),
                    RuleDefinition.rule_type == "taxonomy_field_requirement",
                )
                .order_by(RuleDefinition.key)
            )
        ).all()
        if not rule_version_ids:
            raise AuditConfigurationError(
                "No compiled immutable taxonomy rules exist for this workspace and version"
            )

        previous = await session.scalar(
            select(AuditRun)
            .where(
                AuditRun.workspace_id == workspace_id,
                AuditRun.taxonomy_version == taxonomy_version,
                AuditRun.status == "completed",
            )
            .order_by(AuditRun.completed_at.desc(), AuditRun.id.desc())
            .limit(1)
        )
        if previous is None:
            raise AuditConfigurationError(
                "Incremental audit requires a completed full or incremental baseline"
            )
        if not previous.product_snapshot_hashes or not previous.score_summary:
            raise AuditConfigurationError(
                "Incremental audit requires a baseline created with snapshot state"
            )

        run = AuditRun(
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            previous_run_id=previous.id,
            taxonomy_version=taxonomy_version,
            mode="incremental",
            status="queued",
            source_snapshot_hash=None,
            product_snapshot_hashes={},
            rule_version_set=[str(rule_id) for rule_id in rule_version_ids],
            progress_current=0,
            progress_total=0,
            cancellation_requested=False,
            score_summary={},
            finding_counts={},
            failure_summary={},
        )
        session.add(run)
        await session.flush()
        return run

    async def execute_run(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
    ) -> AuditRun:
        run = await session.scalar(
            select(AuditRun).where(AuditRun.id == run_id).with_for_update()
        )
        if run is None:
            raise AuditRunNotFoundError("Audit run not found")
        if run.status != "queued":
            return run
        if run.cancellation_requested:
            await self._mark_cancelled(session, run)
            return run

        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.failure_summary = {}
        await session.commit()

        try:
            rules = await self._load_rules(session, run)
            all_headers = await self._load_product_headers(session, run)
            previous = await self._previous_run(session, run)
            selected_headers, target_product_ids = await self._select_headers(
                session,
                run=run,
                previous=previous,
                all_headers=all_headers,
            )
            selected_product_ids = {
                product.id for product, _category in selected_headers
            }
            deleted_count = len(target_product_ids - selected_product_ids)
            run.progress_total = len(target_product_ids)
            run.progress_current = deleted_count
            await session.commit()

            evaluations: list[RuleEvaluation] = []
            current_hashes: dict[str, str] = {}
            for offset in range(0, len(selected_headers), AUDIT_BATCH_SIZE):
                await session.refresh(
                    run,
                    attribute_names=["cancellation_requested", "status"],
                )
                if run.cancellation_requested:
                    await self._mark_cancelled(session, run)
                    return run

                batch = selected_headers[offset : offset + AUDIT_BATCH_SIZE]
                snapshots = await self._build_snapshots(session, batch)
                for snapshot in snapshots:
                    payload = _snapshot_bytes(snapshot)
                    current_hashes[str(snapshot.product_id)] = hashlib.sha256(
                        payload
                    ).hexdigest()
                    evaluations.extend(evaluate_product(snapshot, rules))
                run.progress_current = min(
                    deleted_count + offset + len(batch),
                    run.progress_total,
                )
                await session.commit()

            findings = {
                evaluation.finding.fingerprint: evaluation.finding
                for evaluation in evaluations
                if evaluation.finding is not None
            }
            if run.mode == "incremental":
                statuses, resolved_count = await self._reconcile_incremental_findings(
                    session,
                    run=run,
                    findings=findings,
                    target_product_ids=target_product_ids,
                )
            else:
                statuses, resolved_count = await self._reconcile_findings(
                    session,
                    run=run,
                    findings=findings,
                )

            current_health = calculate_health_score(tuple(evaluations))
            target_strings = {str(product_id) for product_id in target_product_ids}
            if run.mode == "incremental":
                if previous is None:
                    raise AuditConfigurationError(
                        "Incremental audit baseline disappeared during execution"
                    )
                contributions = merge_score_contributions(
                    score_contributions_from_summary(previous.score_summary),
                    target_product_ids=target_strings,
                    current=current_health.overall.contributions,
                )
                health = calculate_health_from_contributions(contributions)
                product_hashes = merge_product_snapshot_hashes(
                    previous.product_snapshot_hashes,
                    target_product_ids=target_strings,
                    current=current_hashes,
                )
            else:
                health = current_health
                product_hashes = dict(sorted(current_hashes.items()))

            run.product_snapshot_hashes = product_hashes
            run.source_snapshot_hash = catalog_snapshot_hash(product_hashes)
            run.score_summary = _score_payload(health)
            run.finding_counts = finding_count_summary(
                statuses,
                resolved_count=resolved_count,
            )
            run.progress_current = run.progress_total
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            await session.commit()
            return run
        except Exception as exc:
            await session.rollback()
            failed = await session.get(AuditRun, run_id)
            if failed is not None and failed.status not in {"completed", "cancelled"}:
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                failed.failure_summary = {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:300],
                }
                await session.commit()
            raise

    async def _previous_run(
        self,
        session: AsyncSession,
        run: AuditRun,
    ) -> AuditRun | None:
        if run.previous_run_id is None:
            return None
        return await session.scalar(
            select(AuditRun).where(
                AuditRun.id == run.previous_run_id,
                AuditRun.workspace_id == run.workspace_id,
                AuditRun.status == "completed",
            )
        )

    async def _select_headers(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        previous: AuditRun | None,
        all_headers: Sequence[ProductHeader],
    ) -> tuple[tuple[ProductHeader, ...], set[uuid.UUID]]:
        if run.mode == "full":
            product_ids = {product.id for product, _category in all_headers}
            return tuple(all_headers), product_ids
        if previous is None:
            raise AuditConfigurationError("Incremental audit has no completed baseline")

        target_product_ids = await self._changed_product_ids(
            session,
            run=run,
            previous=previous,
            current_product_ids={product.id for product, _category in all_headers},
        )
        selected = tuple(
            header for header in all_headers if header[0].id in target_product_ids
        )
        return selected, target_product_ids

    async def _changed_product_ids(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        previous: AuditRun,
        current_product_ids: set[uuid.UUID],
    ) -> set[uuid.UUID]:
        cutoff = previous.started_at or previous.created_at
        previous_product_ids: set[uuid.UUID] = set()
        try:
            previous_product_ids = {
                uuid.UUID(product_id)
                for product_id in previous.product_snapshot_hashes
            }
        except ValueError as exc:
            raise AuditConfigurationError(
                "Incremental baseline contains an invalid product identifier"
            ) from exc

        changed: set[uuid.UUID] = previous_product_ids - current_product_ids
        product_queries = (
            select(Product.id).where(
                Product.workspace_id == run.workspace_id,
                Product.updated_at > cutoff,
            ),
            select(ProductVariant.product_id).where(
                ProductVariant.workspace_id == run.workspace_id,
                ProductVariant.updated_at > cutoff,
            ),
            select(ProductAttribute.product_id).where(
                ProductAttribute.workspace_id == run.workspace_id,
                ProductAttribute.updated_at > cutoff,
            ),
        )
        for statement in product_queries:
            changed.update((await session.scalars(statement)).all())

        direct_evidence_ids = (
            await session.scalars(
                select(EvidenceReference.product_id).where(
                    EvidenceReference.workspace_id == run.workspace_id,
                    EvidenceReference.product_id.is_not(None),
                    EvidenceReference.updated_at > cutoff,
                )
            )
        ).all()
        changed.update(
            product_id for product_id in direct_evidence_ids if product_id is not None
        )
        attribute_evidence_ids = (
            await session.scalars(
                select(ProductAttribute.product_id)
                .join(
                    EvidenceReference,
                    EvidenceReference.attribute_id == ProductAttribute.id,
                )
                .where(
                    ProductAttribute.workspace_id == run.workspace_id,
                    EvidenceReference.workspace_id == run.workspace_id,
                    EvidenceReference.updated_at > cutoff,
                )
            )
        ).all()
        changed.update(attribute_evidence_ids)
        return changed

    async def _reconcile_incremental_findings(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        findings: Mapping[str, FindingCandidate],
        target_product_ids: set[uuid.UUID],
    ) -> tuple[list[str], int]:
        previous_run_findings: list[AuditFinding] = []
        if run.previous_run_id is not None:
            previous_run_findings = list(
                (
                    await session.scalars(
                        select(AuditFinding).where(
                            AuditFinding.workspace_id == run.workspace_id,
                            AuditFinding.audit_run_id == run.previous_run_id,
                        )
                    )
                ).all()
            )

        latest_history: dict[str, AuditFinding] = {}
        if findings:
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
            for historical_finding in historical_findings:
                latest_history.setdefault(
                    historical_finding.fingerprint, historical_finding
                )

        now = datetime.now(UTC)
        statuses: list[str] = []
        resolved_count = 0
        for previous_finding in previous_run_findings:
            if previous_finding.product_id not in target_product_ids:
                status = next_finding_status(previous_finding.status)
                statuses.append(status)
                session.add(
                    _copy_finding(
                        previous_finding,
                        run=run,
                        status=status,
                        last_seen_at=now,
                    )
                )
            elif (
                previous_finding.fingerprint not in findings
                and previous_finding.status != "resolved"
            ):
                previous_finding.status = "resolved"
                previous_finding.resolved_at = now
                previous_finding.last_seen_at = now
                resolved_count += 1

        for fingerprint, candidate in sorted(findings.items()):
            latest_finding = latest_history.get(fingerprint)
            status = next_finding_status(
                latest_finding.status if latest_finding is not None else None
            )
            statuses.append(status)
            session.add(
                AuditFinding(
                    workspace_id=run.workspace_id,
                    audit_run_id=run.id,
                    previous_finding_id=(
                        latest_finding.id if latest_finding is not None else None
                    ),
                    rule_version_id=candidate.rule_version_id,
                    product_id=candidate.product_id,
                    variant_id=candidate.variant_id,
                    severity=candidate.severity,
                    title=candidate.title,
                    explanation=candidate.explanation,
                    fingerprint=candidate.fingerprint,
                    status=status,
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
                    first_seen_at=(
                        latest_finding.first_seen_at
                        if latest_finding is not None
                        else now
                    ),
                    last_seen_at=now,
                    resolved_at=None,
                )
            )
        await session.flush()
        return statuses, resolved_count


def _copy_finding(
    finding: AuditFinding,
    *,
    run: AuditRun,
    status: str,
    last_seen_at: datetime,
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
        field_key=finding.field_key,
        affected_value=finding.affected_value,
        business_impact=finding.business_impact,
        remediation_type=finding.remediation_type,
        failure_codes=list(finding.failure_codes),
        evidence=list(finding.evidence),
        first_seen_at=finding.first_seen_at,
        last_seen_at=last_seen_at,
        resolved_at=None,
    )
