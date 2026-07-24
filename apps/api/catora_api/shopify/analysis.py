from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models import (
    AuditEvent,
    AuditFinding,
    BuyerIntent,
    IngestionJob,
    IntentProductMatch,
    Locale,
    Market,
    Organization,
    ReportJob,
    Workspace,
)
from catora_api.diagnostics.service import ASSESSMENT_TYPE
from catora_api.intents.execution import IntentRunService
from catora_api.intents.types import StructuredBuyerIntent

SHOPIFY_ANALYSIS_TEMPLATE_VERSION = "shopify-public-analysis-v1"
_ANALYSIS_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "catora:shopify:analysis")


@dataclass(frozen=True, slots=True)
class ShopifyAnalysisResult:
    report_job: ReportJob
    finding_count: int
    intent_run_count: int
    intent_match_count: int
    confident_match_count: int
    possible_match_missing_data_count: int
    completed_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_value(snapshot: dict[str, object], key: str) -> uuid.UUID | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _job_shopify_snapshot(job: IngestionJob) -> dict[str, object]:
    value = job.checkpoint.get("shopify")
    return value if isinstance(value, dict) else {}


def should_run_shopify_analysis(
    installation: ReportJob,
    ingestion_job: IngestionJob,
) -> bool:
    snapshot = dict(installation.input_snapshot)
    if _uuid_value(snapshot, "last_verified_analysis_report_job_id") is None:
        return True
    shopify = _job_shopify_snapshot(ingestion_job)
    if shopify.get("full_reconciliation") is True:
        return True
    reason = shopify.get("reason")
    if reason in {
        "embedded_app_manual",
        "products/create",
        "products/update",
        "products/delete",
        "public_app_activation",
    }:
        return True
    return ingestion_job.success_count > 0


def _intent_definitions(
    *,
    locale: str,
    market_id: uuid.UUID | None,
) -> tuple[tuple[str, str, StructuredBuyerIntent], ...]:
    definitions: tuple[tuple[str, str, dict[str, object]], ...] = (
        (
            "compact-easy-care-seating",
            "Compact easy-care seating",
            {
                "query": "Which sofas fit a compact room and are easy to care for?",
                "category_keys": ["sofas_sectionals"],
                "hard_constraints": [
                    {
                        "field_key": "width_mm",
                        "operator": "less_than_or_equal",
                        "expected": 1900,
                        "unit": "mm",
                    }
                ],
                "soft_preferences": [
                    {
                        "constraint": {
                            "field_key": "care_instructions",
                            "operator": "contains",
                            "expected": "clean",
                            "unit": None,
                        },
                        "weight": 60,
                    }
                ],
            },
        ),
        (
            "six-seat-dining",
            "Six-seat dining",
            {
                "query": "Which dining products support seating for six people?",
                "category_keys": ["dining_tables_chairs"],
                "hard_constraints": [
                    {
                        "field_key": "seating_capacity",
                        "operator": "greater_than_or_equal",
                        "expected": 6,
                        "unit": None,
                    }
                ],
                "soft_preferences": [],
            },
        ),
        (
            "low-maintenance-outdoor-furniture",
            "Low-maintenance outdoor furniture",
            {
                "query": (
                    "Which outdoor furniture is clearly suitable for outdoor use "
                    "and easy care?"
                ),
                "category_keys": ["outdoor_furniture"],
                "hard_constraints": [
                    {
                        "field_key": "usage_environment",
                        "operator": "one_of",
                        "expected": ["outdoor", "indoor_outdoor"],
                        "unit": None,
                    }
                ],
                "soft_preferences": [
                    {
                        "constraint": {
                            "field_key": "care_instructions",
                            "operator": "contains",
                            "expected": "clean",
                            "unit": None,
                        },
                        "weight": 50,
                    }
                ],
            },
        ),
        (
            "small-space-storage",
            "Small-space storage",
            {
                "query": "Which storage products are narrow enough for a compact home?",
                "category_keys": ["storage_cabinets"],
                "hard_constraints": [
                    {
                        "field_key": "width_mm",
                        "operator": "less_than_or_equal",
                        "expected": 1200,
                        "unit": "mm",
                    }
                ],
                "soft_preferences": [],
            },
        ),
    )
    return tuple(
        (
            key,
            name,
            StructuredBuyerIntent.model_validate(
                {**payload, "market_id": market_id, "locale": locale}
            ),
        )
        for key, name, payload in definitions
    )


async def _workspace_context(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> tuple[str, str, str, uuid.UUID | None]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise RuntimeError("Shopify prospect workspace is unavailable")
    organization = await session.get(Organization, workspace.organization_id)
    market = await session.scalar(
        select(Market)
        .where(Market.workspace_id == workspace_id)
        .order_by(Market.created_at, Market.id)
        .limit(1)
    )
    locale = (
        await session.get(Locale, market.locale_id)
        if market is not None and market.locale_id is not None
        else None
    )
    company_name = organization.name if organization is not None else workspace.name
    market_code = market.code if market is not None else "US"
    locale_code = locale.code if locale is not None else "en-US"
    return company_name, market_code, locale_code, market.id if market is not None else None


async def _ensure_intent(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    key: str,
    name: str,
    structured: StructuredBuyerIntent,
) -> BuyerIntent:
    lineage_id = uuid.uuid5(_ANALYSIS_NAMESPACE, f"{workspace_id}:{key}:v1")
    intent = await session.scalar(
        select(BuyerIntent).where(
            BuyerIntent.workspace_id == workspace_id,
            BuyerIntent.lineage_id == lineage_id,
            BuyerIntent.version == 1,
        )
    )
    payload = structured.model_dump(mode="json")
    if intent is None:
        intent = BuyerIntent(
            workspace_id=workspace_id,
            lineage_id=lineage_id,
            name=name,
            query=structured.query,
            structured_intent=payload,
            source="template",
            version=1,
            approval_status="approved",
        )
        session.add(intent)
        await session.flush()
        return intent
    intent.name = name
    intent.query = structured.query
    intent.structured_intent = payload
    intent.source = "template"
    intent.approval_status = "approved"
    return intent


async def _create_analysis_report(
    session: AsyncSession,
    *,
    installation: ReportJob,
    ingestion_job: IngestionJob,
    audit_run_id: uuid.UUID,
    company_name: str,
    market_code: str,
    locale: str,
    actor_user_id: uuid.UUID,
    assigned_category_count: int,
    ambiguous_category_count: int,
    unclassified_category_count: int,
) -> ReportJob:
    now = _now()
    report = ReportJob(
        id=uuid.uuid4(),
        workspace_id=cast(uuid.UUID, installation.workspace_id),
        report_type=ASSESSMENT_TYPE,
        status="matching",
        input_snapshot={
            "company_name": company_name,
            "operator_user_id": str(actor_user_id),
            "operator_workspace_id": str(installation.workspace_id),
            "market_code": market_code,
            "locale": locale,
            "currency": "USD",
            "retention_days": 90,
            "retention_expires_at": (now + timedelta(days=90)).isoformat(),
            "catalog_source_id": installation.input_snapshot.get("catalog_source_id"),
            "ingestion_job_id": str(ingestion_job.id),
            "audit_run_id": str(audit_run_id),
            "intent_run_ids": [],
            "assigned_category_count": assigned_category_count,
            "ambiguous_category_count": ambiguous_category_count,
            "unclassified_category_count": unclassified_category_count,
            "source": "shopify_public",
            "shopify_installation_id": str(installation.id),
            "analysis_started_at": now.isoformat(),
        },
        template_version=SHOPIFY_ANALYSIS_TEMPLATE_VERSION,
    )
    session.add(report)
    await session.flush()
    return report


async def run_shopify_analysis(
    session: AsyncSession,
    *,
    installation: ReportJob,
    ingestion_job: IngestionJob,
    audit_run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    assigned_category_count: int,
    ambiguous_category_count: int,
    unclassified_category_count: int,
) -> ShopifyAnalysisResult:
    workspace_id = cast(uuid.UUID, installation.workspace_id)
    company_name, market_code, locale, market_id = await _workspace_context(
        session,
        workspace_id,
    )
    report = await _create_analysis_report(
        session,
        installation=installation,
        ingestion_job=ingestion_job,
        audit_run_id=audit_run_id,
        company_name=company_name,
        market_code=market_code,
        locale=locale,
        actor_user_id=actor_user_id,
        assigned_category_count=assigned_category_count,
        ambiguous_category_count=ambiguous_category_count,
        unclassified_category_count=unclassified_category_count,
    )
    installation.input_snapshot = {
        **dict(installation.input_snapshot),
        "analysis_status": "running",
        "analysis_stale": True,
        "analysis_last_attempt_job_id": str(report.id),
        "analysis_last_started_at": _now().isoformat(),
        "analysis_error_type": None,
    }
    await session.commit()

    intent_run_ids: list[str] = []
    intent_match_count = 0
    confident_match_count = 0
    possible_match_missing_data_count = 0
    intent_service = IntentRunService()
    for key, name, structured in _intent_definitions(
        locale=locale,
        market_id=market_id,
    ):
        intent = await _ensure_intent(
            session,
            workspace_id=workspace_id,
            key=key,
            name=name,
            structured=structured,
        )
        result = await intent_service.execute(
            session,
            workspace_id=workspace_id,
            lineage_id=intent.lineage_id,
            intent_version=1,
        )
        intent_run_ids.append(str(result.run.id))
        intent_match_count += len(result.matches)
        confident_match_count += result.summary.confident_match_count
        possible_match_missing_data_count += (
            result.summary.possible_match_missing_data_count
        )

    finding_count = int(
        await session.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.workspace_id == workspace_id,
                AuditFinding.audit_run_id == audit_run_id,
                AuditFinding.status != "resolved",
            )
        )
        or 0
    )
    completed_at = _now()
    report.status = "completed"
    report.input_snapshot = {
        **dict(report.input_snapshot),
        "intent_run_ids": intent_run_ids,
        "finding_count": finding_count,
        "intent_match_count": intent_match_count,
        "confident_match_count": confident_match_count,
        "possible_match_missing_data_count": possible_match_missing_data_count,
        "completed_at": completed_at.isoformat(),
    }
    installation.input_snapshot = {
        **dict(installation.input_snapshot),
        "analysis_status": "completed",
        "analysis_stale": False,
        "analysis_report_job_id": str(report.id),
        "last_verified_analysis_report_job_id": str(report.id),
        "analysis_completed_at": completed_at.isoformat(),
        "last_verified_analysis_at": completed_at.isoformat(),
        "analysis_finding_count": finding_count,
        "analysis_intent_run_count": len(intent_run_ids),
        "analysis_intent_match_count": intent_match_count,
        "analysis_confident_match_count": confident_match_count,
        "analysis_possible_match_missing_data_count": (
            possible_match_missing_data_count
        ),
        "analysis_error_type": None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            event_type="shopify.analysis_completed",
            entity_type="report_job",
            entity_id=report.id,
            payload={
                "installation_id": str(installation.id),
                "ingestion_job_id": str(ingestion_job.id),
                "audit_run_id": str(audit_run_id),
                "finding_count": finding_count,
                "intent_run_count": len(intent_run_ids),
                "intent_match_count": intent_match_count,
            },
        )
    )
    await session.commit()
    return ShopifyAnalysisResult(
        report_job=report,
        finding_count=finding_count,
        intent_run_count=len(intent_run_ids),
        intent_match_count=intent_match_count,
        confident_match_count=confident_match_count,
        possible_match_missing_data_count=possible_match_missing_data_count,
        completed_at=completed_at,
    )


async def mark_shopify_analysis_failed(
    session: AsyncSession,
    *,
    installation: ReportJob,
    error: Exception,
) -> None:
    snapshot = dict(installation.input_snapshot)
    attempt_id = _uuid_value(snapshot, "analysis_last_attempt_job_id")
    report = await session.get(ReportJob, attempt_id) if attempt_id is not None else None
    if report is not None and report.status != "completed":
        report.status = "failed"
        report.input_snapshot = {
            **dict(report.input_snapshot),
            "failure_code": type(error).__name__,
            "failure_detail": "Catora could not refresh this catalog assessment.",
            "failed_at": _now().isoformat(),
        }
    has_verified = _uuid_value(snapshot, "last_verified_analysis_report_job_id") is not None
    installation.input_snapshot = {
        **snapshot,
        "analysis_status": "failed",
        "analysis_stale": has_verified,
        "analysis_error_type": type(error).__name__,
        "analysis_last_failed_at": _now().isoformat(),
    }
    session.add(
        AuditEvent(
            workspace_id=installation.workspace_id,
            actor_user_id=None,
            event_type="shopify.analysis_failed",
            entity_type="report_job",
            entity_id=attempt_id,
            payload={
                "installation_id": str(installation.id),
                "failure_type": type(error).__name__,
                "last_verified_result_preserved": has_verified,
            },
        )
    )
    await session.commit()


async def verified_shopify_analysis_report(
    session: AsyncSession,
    installation: ReportJob,
) -> ReportJob | None:
    report_id = _uuid_value(
        dict(installation.input_snapshot),
        "last_verified_analysis_report_job_id",
    )
    if report_id is None:
        return None
    report = await session.get(ReportJob, report_id)
    if (
        report is None
        or report.workspace_id != installation.workspace_id
        or report.report_type != ASSESSMENT_TYPE
        or report.status != "completed"
        or report.template_version != SHOPIFY_ANALYSIS_TEMPLATE_VERSION
    ):
        return None
    return report
