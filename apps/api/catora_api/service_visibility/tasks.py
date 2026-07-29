from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import cast

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models import (
    AuditEvent,
    CatalogSource,
    ExportArtifact,
    IngestionJob,
    ReportJob,
    SourceRecord,
)
from catora_api.ingestion.factory import connector_for_source
from catora_api.ingestion.service import IngestionService
from catora_api.service_visibility.analysis import analyze_service_site
from catora_api.service_visibility.reporting import (
    build_content_brief_markdown,
    build_findings_csv,
    build_questions_csv,
    build_report_pptx,
)
from catora_api.storage import ObjectStorage

REPORT_TYPE = "service_visibility"
TEMPLATE_VERSION = "service-visibility/v1"


def _uuid(snapshot: dict[str, object], key: str) -> uuid.UUID:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Service visibility report is missing {key}")
    return uuid.UUID(value)


async def _prior_report(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[str | None, set[str]]:
    candidates = list(
        (
            await session.scalars(
                select(ReportJob)
                .where(
                    ReportJob.workspace_id == workspace_id,
                    ReportJob.report_type == REPORT_TYPE,
                    ReportJob.status == "completed",
                    ReportJob.id != report_id,
                )
                .order_by(ReportJob.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    for candidate in candidates:
        snapshot = dict(candidate.input_snapshot)
        if snapshot.get("source_id") != str(source_id):
            continue
        fingerprints = snapshot.get("finding_fingerprints")
        if isinstance(fingerprints, list):
            return str(candidate.id), {
                value for value in fingerprints if isinstance(value, str)
            }
    return None, set()


async def _store_artifact(
    *,
    storage: ObjectStorage,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    artifact_type: str,
    suffix: str,
    content_type: str,
    content: bytes,
) -> str:
    key = f"workspaces/{workspace_id}/service-visibility/{report_id}/{suffix}"
    stored = await storage.put_bytes(key, content, content_type=content_type)
    session.add(
        ExportArtifact(
            workspace_id=workspace_id,
            report_job_id=report_id,
            artifact_type=artifact_type,
            object_key=stored.key,
            checksum=hashlib.sha256(content).hexdigest(),
            size_bytes=stored.size_bytes,
        )
    )
    return stored.key


@shared_task(name="catora.service_visibility.run", ignore_result=True)  # type: ignore[misc]
def run_service_visibility(report_id: str) -> None:
    asyncio.run(_run_service_visibility(uuid.UUID(report_id)))


async def _run_service_visibility(report_id: uuid.UUID) -> None:
    settings = get_settings()
    storage = ObjectStorage(settings)
    async with SessionFactory() as session:
        report_job = await session.get(ReportJob, report_id)
        if report_job is None or report_job.report_type != REPORT_TYPE:
            return
        snapshot = dict(report_job.input_snapshot)
        workspace_id = cast(uuid.UUID, report_job.workspace_id)
        source_id = _uuid(snapshot, "source_id")
        ingestion_job_id = _uuid(snapshot, "ingestion_job_id")
        source = await session.get(CatalogSource, source_id)
        ingestion_job = await session.get(IngestionJob, ingestion_job_id)
        if source is None or ingestion_job is None:
            report_job.status = "failed"
            report_job.input_snapshot = {
                **snapshot,
                "error": "Source or ingestion job is unavailable",
            }
            await session.commit()
            return
        report_job.status = "running"
        await session.commit()
        try:
            connector = await connector_for_source(source, storage)
            ingestion = await IngestionService(page_size=100).run(
                session,
                source=source,
                job=ingestion_job,
                connector=connector,
            )
            if ingestion.status not in {"completed", "partially_completed"}:
                raise RuntimeError("Service website ingestion did not complete")
            records = list(
                (
                    await session.scalars(
                        select(SourceRecord)
                        .where(
                            SourceRecord.workspace_id == workspace_id,
                            SourceRecord.catalog_source_id == source.id,
                            SourceRecord.last_seen_job_id == ingestion_job.id,
                            SourceRecord.record_type == "service_page",
                        )
                        .order_by(SourceRecord.external_id, SourceRecord.id)
                    )
                ).all()
            )
            prior_report_id, prior_fingerprints = await _prior_report(
                session=session,
                workspace_id=workspace_id,
                source_id=source.id,
                report_id=report_job.id,
            )
            site_url = str(source.config.get("site_url") or "")
            report = analyze_service_site(
                source_id=str(source.id),
                ingestion_job_id=str(ingestion_job.id),
                site_url=site_url,
                records=[
                    (dict(record.payload), record.content_hash, record.source_updated_at)
                    for record in records
                ],
                prior_report_id=prior_report_id,
                prior_fingerprints=prior_fingerprints,
            )
            report_json = report.model_dump_json(indent=2).encode()
            artifacts = {
                "report_json": await _store_artifact(
                    storage=storage,
                    session=session,
                    workspace_id=workspace_id,
                    report_id=report_job.id,
                    artifact_type="service_visibility_json",
                    suffix="service-visibility-report.json",
                    content_type="application/json",
                    content=report_json,
                ),
                "findings_csv": await _store_artifact(
                    storage=storage,
                    session=session,
                    workspace_id=workspace_id,
                    report_id=report_job.id,
                    artifact_type="service_visibility_findings_csv",
                    suffix="service-visibility-findings.csv",
                    content_type="text/csv",
                    content=build_findings_csv(report).encode(),
                ),
                "questions_csv": await _store_artifact(
                    storage=storage,
                    session=session,
                    workspace_id=workspace_id,
                    report_id=report_job.id,
                    artifact_type="service_visibility_questions_csv",
                    suffix="service-visibility-buyer-questions.csv",
                    content_type="text/csv",
                    content=build_questions_csv(report).encode(),
                ),
                "content_brief": await _store_artifact(
                    storage=storage,
                    session=session,
                    workspace_id=workspace_id,
                    report_id=report_job.id,
                    artifact_type="service_visibility_content_brief",
                    suffix="service-visibility-content-brief.md",
                    content_type="text/markdown",
                    content=build_content_brief_markdown(report).encode(),
                ),
                "presentation": await _store_artifact(
                    storage=storage,
                    session=session,
                    workspace_id=workspace_id,
                    report_id=report_job.id,
                    artifact_type="service_visibility_pptx",
                    suffix="service-visibility-assessment.pptx",
                    content_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation"
                    ),
                    content=build_report_pptx(report),
                ),
            }
            report_job.status = "completed"
            report_job.input_snapshot = {
                **snapshot,
                "completed_at": datetime.now(UTC).isoformat(),
                "page_count": len(report.site.pages),
                "finding_count": len(report.findings),
                "question_count": len(report.buyer_questions),
                "scorecard": report.scorecard.model_dump(),
                "continuity": report.continuity.model_dump(),
                "executive_summary": report.executive_summary,
                "finding_fingerprints": [finding.fingerprint for finding in report.findings],
                "artifacts": artifacts,
                "error": None,
            }
            source.config = {
                **dict(source.config),
                "active_report_id": None,
                "last_report_id": str(report_job.id),
                "last_completed_at": datetime.now(UTC).isoformat(),
            }
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=None,
                    event_type="service_visibility.report_completed",
                    entity_type="report_job",
                    entity_id=report_job.id,
                    payload={
                        "source_id": str(source.id),
                        "page_count": len(report.site.pages),
                        "finding_count": len(report.findings),
                        "overall_score": report.scorecard.overall,
                    },
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            failed_report = await session.get(ReportJob, report_id)
            failed_source = await session.get(CatalogSource, source_id)
            if failed_report is not None:
                current = dict(failed_report.input_snapshot)
                failed_report.status = "failed"
                failed_report.input_snapshot = {
                    **current,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            if failed_source is not None:
                failed_source.config = {
                    **dict(failed_source.config),
                    "active_report_id": None,
                }
            await session.commit()


@shared_task(name="catora.service_visibility.monitor", ignore_result=True)  # type: ignore[misc]
def monitor_service_visibility() -> None:
    asyncio.run(_monitor_service_visibility())


async def _monitor_service_visibility() -> None:
    settings = get_settings()
    if (
        not settings.service_visibility_enabled
        or not settings.service_visibility_monitoring_enabled
    ):
        return
    async with SessionFactory() as session:
        sources = list(
            (
                await session.scalars(
                    select(CatalogSource).where(
                        CatalogSource.source_type == "wordpress",
                        CatalogSource.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        queued: list[str] = []
        for source in sources:
            config = dict(source.config)
            if config.get("monitoring_enabled") is not True or config.get("active_report_id"):
                continue
            job = IngestionJob(
                workspace_id=source.workspace_id,
                catalog_source_id=source.id,
                status="queued",
                checkpoint={},
            )
            session.add(job)
            await session.flush()
            report = ReportJob(
                workspace_id=source.workspace_id,
                report_type=REPORT_TYPE,
                status="queued",
                template_version=TEMPLATE_VERSION,
                input_snapshot={
                    "source_id": str(source.id),
                    "ingestion_job_id": str(job.id),
                    "trigger": "monitoring",
                },
            )
            session.add(report)
            await session.flush()
            source.config = {**config, "active_report_id": str(report.id)}
            queued.append(str(report.id))
        await session.commit()
    for report_id in queued:
        run_service_visibility.delay(report_id)
