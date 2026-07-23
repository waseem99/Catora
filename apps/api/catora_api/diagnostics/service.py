from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import (
    AuditEvent,
    AuditFinding,
    IngestionJob,
    IntentProductMatch,
    Locale,
    Market,
    Membership,
    Organization,
    Product,
    ProductVariant,
    ReportJob,
    Storefront,
    Workspace,
)
from catora_api.schemas.diagnostics import (
    DiagnosticCounts,
    DiagnosticCreateRequest,
    DiagnosticRejection,
    DiagnosticRejectionList,
    DiagnosticStatus,
    DiagnosticView,
)

ASSESSMENT_TYPE = "prospect_diagnostic"
TEMPLATE_VERSION = "prospect-diagnostic-v1"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")

_STAGE_DETAILS: dict[str, tuple[str, str]] = {
    "awaiting_upload": (
        "Upload catalog",
        "The prospect workspace is ready for a Shopify product CSV.",
    ),
    "queued": (
        "Queued",
        "The catalog assessment is queued for the Catora worker.",
    ),
    "ingesting": (
        "Importing catalog",
        "Catora is validating and importing Shopify product rows.",
    ),
    "normalizing": (
        "Normalizing catalog",
        "Products, variants and evidence are being canonicalized.",
    ),
    "categorizing": (
        "Assigning taxonomy",
        "Products are being classified against the furniture taxonomy.",
    ),
    "auditing": (
        "Running deterministic audit",
        "Evidence-backed catalog requirements are being evaluated.",
    ),
    "matching": (
        "Testing buyer intents",
        "Prepared furniture buying scenarios are being evaluated.",
    ),
    "preparing_reports": (
        "Preparing deliverables",
        "Persisted findings and matches are being reconciled.",
    ),
    "completed": (
        "Assessment complete",
        "The branded assessment and operational backlog are ready.",
    ),
    "failed": (
        "Assessment needs attention",
        "The assessment stopped safely and can be inspected or retried.",
    ),
    "deleting": (
        "Deleting assessment",
        "Catalog data and the isolated prospect workspace are being removed.",
    ),
}


class DiagnosticNotFoundError(LookupError):
    pass


def _slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.casefold()).strip("-")
    return normalized[:70] or "prospect"


def _snapshot_uuid(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _snapshot_uuid_list(snapshot: dict[str, object], key: str) -> list[uuid.UUID]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    result: list[uuid.UUID] = []
    for item in value:
        if not isinstance(item, str):
            continue
        try:
            result.append(uuid.UUID(item))
        except ValueError:
            continue
    return result


def _snapshot_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key, 0)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _snapshot_text(snapshot: dict[str, object], key: str, default: str = "") -> str:
    value = snapshot.get(key)
    return value if isinstance(value, str) else default


def _snapshot_datetime(snapshot: dict[str, object], key: str) -> datetime | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DiagnosticService:
    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    async def create(
        self,
        session: AsyncSession,
        *,
        actor_user_id: uuid.UUID,
        actor_role: str,
        operator_workspace_id: uuid.UUID,
        payload: DiagnosticCreateRequest,
    ) -> ReportJob:
        assessment_id = uuid.uuid4()
        suffix = assessment_id.hex[:8]
        company_slug = _slug(payload.company_name)
        organization = Organization(
            name=payload.company_name,
            slug=f"diagnostic-{company_slug}-{suffix}",
        )
        session.add(organization)
        await session.flush()

        workspace = Workspace(
            organization_id=organization.id,
            name=f"{payload.company_name} — Catora Diagnostic",
            slug="catalog-diagnostic",
        )
        session.add(workspace)
        await session.flush()

        membership_role = actor_role if actor_role in {"owner", "admin"} else "analyst"
        session.add(
            Membership(
                organization_id=organization.id,
                workspace_id=workspace.id,
                user_id=actor_user_id,
                role=membership_role,
            )
        )

        locale_parts = payload.locale.split("-", 1)
        locale = Locale(
            workspace_id=workspace.id,
            code=payload.locale,
            language=locale_parts[0],
            region=locale_parts[1] if len(locale_parts) == 2 else None,
        )
        session.add(locale)
        await session.flush()

        storefront = Storefront(
            workspace_id=workspace.id,
            name=f"{payload.company_name} catalog export",
            domain=(
                payload.storefront_domain
                or f"diagnostic-{assessment_id.hex[:12]}.catalog.local"
            ),
            platform="shopify_csv",
        )
        session.add(storefront)
        await session.flush()

        market = Market(
            workspace_id=workspace.id,
            storefront_id=storefront.id,
            locale_id=locale.id,
            code=payload.market_code,
            currency=payload.currency,
            name=f"{payload.market_code} diagnostic market",
        )
        session.add(market)
        await session.flush()

        now = self.now()
        assessment = ReportJob(
            id=assessment_id,
            workspace_id=workspace.id,
            report_type=ASSESSMENT_TYPE,
            status="awaiting_upload",
            input_snapshot={
                "company_name": payload.company_name,
                "organization_id": str(organization.id),
                "operator_user_id": str(actor_user_id),
                "operator_workspace_id": str(operator_workspace_id),
                "market_id": str(market.id),
                "market_code": payload.market_code,
                "locale": payload.locale,
                "currency": payload.currency,
                "storefront_id": str(storefront.id),
                "storefront_domain": storefront.domain,
                "authorization_confirmed": True,
                "authorization_confirmed_at": now.isoformat(),
                "retention_days": payload.retention_days,
                "retention_expires_at": (
                    now + timedelta(days=payload.retention_days)
                ).isoformat(),
                "assigned_category_count": 0,
                "ambiguous_category_count": 0,
                "unclassified_category_count": 0,
            },
            template_version=TEMPLATE_VERSION,
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace.id,
                actor_user_id=actor_user_id,
                event_type="diagnostic.created",
                entity_type="report_job",
                entity_id=assessment.id,
                payload={
                    "operator_workspace_id": str(operator_workspace_id),
                    "company_name": payload.company_name,
                    "market_code": payload.market_code,
                    "locale": payload.locale,
                    "currency": payload.currency,
                    "retention_days": payload.retention_days,
                    "authorization_confirmed": True,
                },
            )
        )
        await session.commit()
        await session.refresh(assessment)
        return assessment

    async def get(self, session: AsyncSession, assessment_id: uuid.UUID) -> ReportJob:
        assessment = await session.scalar(
            select(ReportJob).where(
                ReportJob.id == assessment_id,
                ReportJob.report_type == ASSESSMENT_TYPE,
            )
        )
        if assessment is None:
            raise DiagnosticNotFoundError("Prospect diagnostic not found")
        return assessment

    async def set_status(
        self,
        session: AsyncSession,
        assessment: ReportJob,
        status: DiagnosticStatus,
        **snapshot_updates: object,
    ) -> None:
        snapshot = {**dict(assessment.input_snapshot), **snapshot_updates}
        if status == "completed" and "completed_at" not in snapshot:
            snapshot["completed_at"] = self.now().isoformat()
        assessment.status = status
        assessment.input_snapshot = snapshot
        await session.commit()

    async def view(
        self,
        session: AsyncSession,
        assessment: ReportJob,
    ) -> DiagnosticView:
        snapshot = dict(assessment.input_snapshot)
        workspace = await session.get(
            Workspace,
            cast(uuid.UUID, assessment.workspace_id),
        )
        if workspace is None:
            raise DiagnosticNotFoundError("Prospect diagnostic workspace not found")

        job_id = _snapshot_uuid(snapshot, "ingestion_job_id")
        job = await session.get(IngestionJob, job_id) if job_id is not None else None
        audit_run_id = _snapshot_uuid(snapshot, "audit_run_id")
        intent_run_ids = _snapshot_uuid_list(snapshot, "intent_run_ids")

        product_count = int(
            await session.scalar(
                select(func.count(Product.id)).where(
                    Product.workspace_id == workspace.id,
                    Product.deleted_at.is_(None),
                )
            )
            or 0
        )
        variant_count = int(
            await session.scalar(
                select(func.count(ProductVariant.id)).where(
                    ProductVariant.workspace_id == workspace.id,
                    ProductVariant.deleted_at.is_(None),
                )
            )
            or 0
        )
        finding_count = 0
        if audit_run_id is not None:
            finding_count = int(
                await session.scalar(
                    select(func.count(AuditFinding.id)).where(
                        AuditFinding.workspace_id == workspace.id,
                        AuditFinding.audit_run_id == audit_run_id,
                        AuditFinding.status != "resolved",
                    )
                )
                or 0
            )
        intent_match_count = 0
        if intent_run_ids:
            intent_match_count = int(
                await session.scalar(
                    select(func.count(IntentProductMatch.id)).where(
                        IntentProductMatch.workspace_id == workspace.id,
                        IntentProductMatch.intent_run_id.in_(intent_run_ids),
                    )
                )
                or 0
            )

        stage, detail = _STAGE_DETAILS.get(
            assessment.status,
            (
                assessment.status.replace("_", " ").title(),
                "Catora is reconciling assessment state.",
            ),
        )
        counts = DiagnosticCounts(
            processed_rows=job.processed_count if job is not None else 0,
            accepted_rows=job.success_count if job is not None else 0,
            rejected_rows=job.rejection_count if job is not None else 0,
            warning_count=job.warning_count if job is not None else 0,
            product_count=product_count,
            variant_count=variant_count,
            assigned_category_count=_snapshot_int(
                snapshot,
                "assigned_category_count",
            ),
            ambiguous_category_count=_snapshot_int(
                snapshot,
                "ambiguous_category_count",
            ),
            unclassified_category_count=_snapshot_int(
                snapshot,
                "unclassified_category_count",
            ),
            finding_count=finding_count,
            intent_run_count=len(intent_run_ids),
            intent_match_count=intent_match_count,
        )
        diagnostic_status = cast(DiagnosticStatus, assessment.status)
        return DiagnosticView(
            id=assessment.id,
            workspace_id=workspace.id,
            organization_id=workspace.organization_id,
            company_name=_snapshot_text(snapshot, "company_name", workspace.name),
            status=diagnostic_status,
            current_stage=stage,
            detail=detail,
            market_code=_snapshot_text(snapshot, "market_code"),
            locale=_snapshot_text(snapshot, "locale"),
            currency=_snapshot_text(snapshot, "currency"),
            retention_expires_at=(
                _snapshot_datetime(snapshot, "retention_expires_at")
                or assessment.created_at
            ),
            counts=counts,
            created_at=assessment.created_at,
            updated_at=assessment.updated_at,
            completed_at=_snapshot_datetime(snapshot, "completed_at"),
            failure_code=_snapshot_text(snapshot, "failure_code") or None,
            failure_detail=_snapshot_text(snapshot, "failure_detail") or None,
            ingestion_job_id=job_id,
            audit_run_id=audit_run_id,
            intent_run_ids=intent_run_ids,
            result_path=f"/workspace/{workspace.id}/diagnostic/{assessment.id}",
            report_path=(
                f"/api/v1/prospect-diagnostics/{assessment.id}/report.pptx"
            ),
            backlog_path=(
                f"/api/v1/prospect-diagnostics/{assessment.id}/backlog.csv"
            ),
            rejection_path=(
                f"/api/v1/prospect-diagnostics/{assessment.id}/rejections"
            ),
        )

    async def rejection_list(
        self,
        session: AsyncSession,
        assessment: ReportJob,
    ) -> DiagnosticRejectionList:
        snapshot = dict(assessment.input_snapshot)
        job_id = _snapshot_uuid(snapshot, "ingestion_job_id")
        job = await session.get(IngestionJob, job_id) if job_id is not None else None
        samples: list[DiagnosticRejection] = []
        if job is not None:
            raw_samples = job.checkpoint.get("rejection_samples", [])
            if isinstance(raw_samples, list):
                for item in raw_samples:
                    if not isinstance(item, dict):
                        continue
                    row_number = item.get("row_number")
                    reason = item.get("reason")
                    raw_payload = item.get("raw_payload")
                    if (
                        not isinstance(row_number, int)
                        or row_number < 1
                        or not isinstance(reason, str)
                    ):
                        continue
                    payload = raw_payload if isinstance(raw_payload, dict) else {}
                    handle = payload.get("Handle")
                    sku = payload.get("Variant SKU")
                    samples.append(
                        DiagnosticRejection(
                            row_number=row_number,
                            reason=reason,
                            product_handle=(
                                handle
                                if isinstance(handle, str) and handle
                                else None
                            ),
                            variant_sku=(
                                sku if isinstance(sku, str) and sku else None
                            ),
                        )
                    )
        return DiagnosticRejectionList(
            items=samples,
            total_rejected=job.rejection_count if job is not None else 0,
            sample_limit=100,
        )
