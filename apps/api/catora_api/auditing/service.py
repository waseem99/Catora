from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing.lifecycle import finding_count_summary, next_finding_status
from catora_api.auditing.rules import TaxonomyFieldRule, evaluate_product
from catora_api.auditing.scoring import CatalogHealthScore, DimensionScore, calculate_health_score
from catora_api.auditing.types import (
    AttributeSnapshot,
    AttributeValue,
    EvidenceSnapshot,
    FindingCandidate,
    ProductAuditSnapshot,
    RuleEvaluation,
    VariantAuditSnapshot,
)
from catora_api.db.models.audit import AuditFinding, AuditRun, RuleDefinition, RuleVersion
from catora_api.db.models.catalog import (
    Category,
    EvidenceReference,
    Product,
    ProductAttribute,
    ProductVariant,
)

AUDIT_BATCH_SIZE = 250
ACTIVE_AUDIT_STATUSES = ("queued", "running")


class AuditRunNotFoundError(LookupError):
    pass


class AuditRunConflictError(ValueError):
    pass


class AuditConfigurationError(ValueError):
    pass


type ProductHeader = tuple[Product, Category]
type DatabaseValue = dict[str, object] | list[object] | str | int | float | bool | None


class AuditRunService:
    async def create_run(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        taxonomy_version: str,
        mode: str,
    ) -> AuditRun:
        if mode != "full":
            raise AuditConfigurationError("Only full audit runs are supported")
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
        run = AuditRun(
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            previous_run_id=previous.id if previous is not None else None,
            taxonomy_version=taxonomy_version,
            mode=mode,
            status="queued",
            source_snapshot_hash=None,
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

    async def request_cancellation(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> AuditRun:
        run = await session.scalar(
            select(AuditRun).where(
                AuditRun.id == run_id,
                AuditRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise AuditRunNotFoundError("Audit run not found")
        if run.status not in ACTIVE_AUDIT_STATUSES:
            raise AuditRunConflictError("Only an active audit run can be cancelled")
        run.cancellation_requested = True
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
            headers = await self._load_product_headers(session, run)
            run.progress_total = len(headers)
            run.progress_current = 0
            await session.commit()

            evaluations: list[RuleEvaluation] = []
            snapshot_hasher = hashlib.sha256()
            for offset in range(0, len(headers), AUDIT_BATCH_SIZE):
                await session.refresh(
                    run,
                    attribute_names=["cancellation_requested", "status"],
                )
                if run.cancellation_requested:
                    await self._mark_cancelled(session, run)
                    return run

                batch = headers[offset : offset + AUDIT_BATCH_SIZE]
                snapshots = await self._build_snapshots(session, batch)
                for snapshot in snapshots:
                    snapshot_hasher.update(_snapshot_bytes(snapshot))
                    evaluations.extend(evaluate_product(snapshot, rules))
                run.progress_current = min(offset + len(batch), run.progress_total)
                await session.commit()

            findings = {
                evaluation.finding.fingerprint: evaluation.finding
                for evaluation in evaluations
                if evaluation.finding is not None
            }
            statuses, resolved_count = await self._reconcile_findings(
                session,
                run=run,
                findings=findings,
            )
            health = calculate_health_score(tuple(evaluations))
            run.source_snapshot_hash = snapshot_hasher.hexdigest()
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

    async def _load_rules(
        self,
        session: AsyncSession,
        run: AuditRun,
    ) -> tuple[TaxonomyFieldRule, ...]:
        rule_ids = [uuid.UUID(value) for value in run.rule_version_set]
        rows = (
            await session.execute(
                select(RuleVersion, RuleDefinition)
                .join(
                    RuleDefinition,
                    RuleDefinition.id == RuleVersion.rule_definition_id,
                )
                .where(
                    RuleVersion.workspace_id == run.workspace_id,
                    RuleVersion.id.in_(rule_ids),
                    RuleVersion.version == run.taxonomy_version,
                    RuleVersion.is_immutable.is_(True),
                    RuleDefinition.rule_type == "taxonomy_field_requirement",
                )
                .order_by(RuleDefinition.key)
            )
        ).all()
        if len(rows) != len(rule_ids):
            raise AuditConfigurationError("Audit rule version set is missing or changed")
        return tuple(
            TaxonomyFieldRule.from_specification(
                rule_version_id=version.id,
                rule_key=definition.key,
                rule_version=version.version,
                specification=version.specification,
            )
            for version, definition in rows
        )

    async def _load_product_headers(
        self,
        session: AsyncSession,
        run: AuditRun,
    ) -> tuple[ProductHeader, ...]:
        rows = (
            await session.execute(
                select(Product, Category)
                .join(Category, Category.id == Product.primary_category_id)
                .where(
                    Product.workspace_id == run.workspace_id,
                    Product.deleted_at.is_(None),
                    Product.status == "active",
                    Category.workspace_id == run.workspace_id,
                    Category.taxonomy_version == run.taxonomy_version,
                    Category.is_immutable.is_(True),
                )
                .order_by(Product.id)
            )
        ).all()
        return tuple((product, category) for product, category in rows)

    async def _build_snapshots(
        self,
        session: AsyncSession,
        headers: Sequence[ProductHeader],
    ) -> tuple[ProductAuditSnapshot, ...]:
        if not headers:
            return ()
        product_ids = [product.id for product, _category in headers]
        variants = (
            await session.scalars(
                select(ProductVariant)
                .where(
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.deleted_at.is_(None),
                )
                .order_by(ProductVariant.product_id, ProductVariant.id)
            )
        ).all()
        attributes = (
            await session.scalars(
                select(ProductAttribute)
                .where(ProductAttribute.product_id.in_(product_ids))
                .order_by(
                    ProductAttribute.product_id,
                    ProductAttribute.variant_id,
                    ProductAttribute.key,
                )
            )
        ).all()
        attribute_ids = [attribute.id for attribute in attributes]
        evidence = []
        if attribute_ids:
            evidence = (
                await session.scalars(
                    select(EvidenceReference)
                    .where(EvidenceReference.attribute_id.in_(attribute_ids))
                    .order_by(
                        EvidenceReference.attribute_id,
                        EvidenceReference.field_path,
                        EvidenceReference.id,
                    )
                )
            ).all()

        evidence_by_attribute: dict[uuid.UUID, list[EvidenceReference]] = defaultdict(list)
        for reference in evidence:
            if reference.attribute_id is not None:
                evidence_by_attribute[reference.attribute_id].append(reference)

        attributes_by_product: dict[uuid.UUID, list[ProductAttribute]] = defaultdict(list)
        for attribute in attributes:
            attributes_by_product[attribute.product_id].append(attribute)
        variants_by_product: dict[uuid.UUID, list[ProductVariant]] = defaultdict(list)
        for variant in variants:
            variants_by_product[variant.product_id].append(variant)

        snapshots: list[ProductAuditSnapshot] = []
        for product, category in headers:
            product_attributes: dict[str, AttributeSnapshot] = {}
            variant_attributes: dict[uuid.UUID, dict[str, AttributeSnapshot]] = defaultdict(dict)
            present_count = 0
            evidenced_count = 0
            for attribute in attributes_by_product[product.id]:
                snapshot = _attribute_snapshot(
                    attribute,
                    evidence_by_attribute.get(attribute.id, []),
                )
                if attribute.value_state == "present":
                    present_count += 1
                    if snapshot.evidence:
                        evidenced_count += 1
                if attribute.variant_id is None:
                    product_attributes[attribute.key] = snapshot
                else:
                    variant_attributes[attribute.variant_id][attribute.key] = snapshot
            coverage = (
                (evidenced_count * 10000 + present_count // 2) // present_count
                if present_count
                else 0
            )
            variant_snapshots = tuple(
                VariantAuditSnapshot(
                    variant_id=variant.id,
                    attributes=variant_attributes.get(variant.id, {}),
                )
                for variant in variants_by_product[product.id]
            )
            snapshots.append(
                ProductAuditSnapshot(
                    product_id=product.id,
                    category_key=category.key,
                    attributes=product_attributes,
                    variants=variant_snapshots,
                    source_coverage_basis_points=coverage,
                )
            )
        return tuple(snapshots)

    async def _reconcile_findings(
        self,
        session: AsyncSession,
        *,
        run: AuditRun,
        findings: Mapping[str, FindingCandidate],
    ) -> tuple[list[str], int]:
        previous_findings: list[AuditFinding] = []
        if run.previous_run_id is not None:
            previous_findings = list(
                (
                    await session.scalars(
                        select(AuditFinding).where(
                            AuditFinding.workspace_id == run.workspace_id,
                            AuditFinding.audit_run_id == run.previous_run_id,
                        )
                    )
                ).all()
            )
        previous_by_fingerprint = {
            finding.fingerprint: finding for finding in previous_findings
        }
        now = datetime.now(UTC)
        resolved_count = 0
        for previous in previous_findings:
            if previous.fingerprint not in findings and previous.status != "resolved":
                previous.status = "resolved"
                previous.resolved_at = now
                previous.last_seen_at = now
                resolved_count += 1

        statuses: list[str] = []
        for fingerprint, candidate in sorted(findings.items()):
            previous = previous_by_fingerprint.get(fingerprint)
            status = next_finding_status(previous.status if previous is not None else None)
            statuses.append(status)
            session.add(
                AuditFinding(
                    workspace_id=run.workspace_id,
                    audit_run_id=run.id,
                    previous_finding_id=previous.id if previous is not None else None,
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
                        previous.first_seen_at if previous is not None else now
                    ),
                    last_seen_at=now,
                    resolved_at=None,
                )
            )
        await session.flush()
        return statuses, resolved_count

    async def _mark_cancelled(self, session: AsyncSession, run: AuditRun) -> None:
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        await session.commit()


def _attribute_snapshot(
    attribute: ProductAttribute,
    evidence: Sequence[EvidenceReference],
) -> AttributeSnapshot:
    return AttributeSnapshot(
        key=attribute.key,
        value=cast(AttributeValue, attribute.value),
        value_type=attribute.value_type,
        value_state=attribute.value_state,
        unit=attribute.unit,
        locale=attribute.locale,
        evidence=tuple(
            EvidenceSnapshot(
                source_record_id=reference.source_record_id,
                field_path=reference.field_path,
                excerpt=reference.excerpt,
                checksum=reference.checksum,
            )
            for reference in evidence
        ),
    )


def _database_value(value: AttributeValue) -> DatabaseValue:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return list(value)
    return cast(str | int | float | bool | None, value)


def _snapshot_bytes(snapshot: ProductAuditSnapshot) -> bytes:
    payload = {
        "product_id": str(snapshot.product_id),
        "category_key": snapshot.category_key,
        "source_coverage_basis_points": snapshot.source_coverage_basis_points,
        "attributes": {
            key: _attribute_payload(value)
            for key, value in sorted(snapshot.attributes.items())
        },
        "variants": [
            {
                "variant_id": str(variant.variant_id),
                "attributes": {
                    key: _attribute_payload(value)
                    for key, value in sorted(variant.attributes.items())
                },
            }
            for variant in snapshot.variants
        ],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _attribute_payload(attribute: AttributeSnapshot) -> dict[str, object]:
    return {
        "value": attribute.value,
        "value_type": attribute.value_type,
        "value_state": attribute.value_state,
        "unit": attribute.unit,
        "locale": attribute.locale,
        "evidence": [
            {
                "source_record_id": str(item.source_record_id),
                "field_path": item.field_path,
                "excerpt": item.excerpt,
                "checksum": item.checksum,
            }
            for item in attribute.evidence
        ],
    }


def _score_payload(health: CatalogHealthScore) -> dict[str, object]:
    return {
        "formula_version": "weighted-health-v1",
        "overall": _dimension_payload(health.overall),
        "dimensions": {
            key: _dimension_payload(value)
            for key, value in health.dimensions.items()
        },
    }


def _dimension_payload(score: DimensionScore) -> dict[str, object]:
    return {
        "score_basis_points": score.score_basis_points,
        "confidence_basis_points": score.confidence_basis_points,
        "eligible_weight": score.eligible_weight,
        "evaluated_weight": score.evaluated_weight,
        "passed_weight": score.passed_weight,
        "contributions": [
            {
                "rule_key": item.rule_key,
                "rule_version_id": item.rule_version_id,
                "product_id": item.product_id,
                "variant_id": item.variant_id,
                "check_key": item.check_key,
                "dimension": item.dimension,
                "weight": item.weight,
                "outcome": item.outcome,
                "coverage_basis_points": item.coverage_basis_points,
            }
            for item in score.contributions
        ],
    }
