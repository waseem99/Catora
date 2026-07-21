from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._stateful_service import (
    StatefulAuditRunService as _BaseStatefulAuditRunService,
)
from catora_api.auditing.custom_rules import (
    CustomAuditRuleConfigurationError,
    current_audit_rule_version_ids,
    evaluate_custom_relationship_rules,
    load_audit_rule_set,
)
from catora_api.auditing.incremental import (
    IncrementalStateError,
    catalog_snapshot_hash,
    merge_product_snapshot_hashes,
    merge_score_contributions,
    score_contributions_from_summary,
)
from catora_api.auditing.lifecycle import finding_count_summary
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
    _score_payload,
    _snapshot_bytes,
)
from catora_api.auditing.types import RuleEvaluation
from catora_api.db.models.audit import AuditRun


class StatefulAuditRunService(_BaseStatefulAuditRunService):
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
            rule_version_ids = await current_audit_rule_version_ids(
                session,
                workspace_id=workspace_id,
                taxonomy_version=taxonomy_version,
            )
            run.rule_version_set = [str(rule_id) for rule_id in rule_version_ids]
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

        rule_version_ids = await current_audit_rule_version_ids(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
        )
        if not rule_version_ids:
            raise AuditConfigurationError(
                "No immutable audit rules exist for this workspace and version"
            )
        current_rule_version_set = [str(rule_id) for rule_id in rule_version_ids]

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
        if previous.rule_version_set != current_rule_version_set:
            raise AuditConfigurationError(
                "Incremental audit requires an unchanged rule-version set; run a full audit"
            )
        try:
            score_contributions_from_summary(previous.score_summary)
        except IncrementalStateError as exc:
            raise AuditConfigurationError(str(exc)) from exc

        run = AuditRun(
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            previous_run_id=previous.id,
            taxonomy_version=taxonomy_version,
            mode="incremental",
            status="queued",
            source_snapshot_hash=None,
            product_snapshot_hashes={},
            rule_version_set=current_rule_version_set,
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
            try:
                rule_set = await load_audit_rule_set(session, run)
            except CustomAuditRuleConfigurationError as exc:
                raise AuditConfigurationError(str(exc)) from exc
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
                    evaluations.extend(
                        evaluate_product(snapshot, rule_set.field_rules)
                    )
                    evaluations.extend(
                        evaluate_custom_relationship_rules(
                            snapshot,
                            rule_set.custom_relationship_rules,
                        )
                    )
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
