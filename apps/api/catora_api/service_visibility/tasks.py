# ruff: noqa: E501
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from celery import shared_task
from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models import AuditEvent
from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.service_visibility.crawler import crawl_site
from catora_api.service_visibility.engine import build_scorecard


@shared_task(name="catora.service_visibility.run", ignore_result=True)  # type: ignore[misc]
def run(job_id: str) -> None:
    asyncio.run(_run(uuid.UUID(job_id)))


async def _run(job_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None or job.status not in {"queued", "validating", "running"}:
            return
        source = await session.get(CatalogSource, job.catalog_source_id)
        if source is None:
            job.status = "failed"
            job.completed_at = datetime.now(UTC)
            await session.commit()
            return
        service_config = source.config.get("service_visibility")
        config = dict(service_config) if isinstance(service_config, dict) else {}
        try:
            job.status = "running"
            job.started_at = job.started_at or datetime.now(UTC)
            job.checkpoint = {**dict(job.checkpoint), "phase": "crawling"}
            source.status = "syncing"
            await session.commit()
            pages = await crawl_site(
                str(source.config.get("start_url") or ""),
                max_pages=int(config.get("max_pages") or 150),
            )
            for page in pages:
                existing = await session.scalar(
                    select(SourceRecord).where(
                        SourceRecord.catalog_source_id == source.id,
                        SourceRecord.external_id == str(page.canonical_url),
                        SourceRecord.content_hash == page.content_hash,
                    )
                )
                if existing is not None:
                    existing.last_seen_job_id = job.id
                    continue
                session.add(
                    SourceRecord(
                        workspace_id=source.workspace_id,
                        catalog_source_id=source.id,
                        ingestion_job_id=job.id,
                        last_seen_job_id=job.id,
                        external_id=str(page.canonical_url),
                        record_type="service_page",
                        payload=page.model_dump(mode="json", by_alias=True),
                        content_hash=page.content_hash,
                        source_updated_at=page.updated_at,
                    )
                )
            scorecard = build_scorecard(source.id, job.id, pages)
            job.status = "completed" if pages else "partially_completed"
            job.processed_count = len(pages)
            job.success_count = len(pages)
            job.warning_count = 0 if pages else 1
            job.checkpoint = {
                "score_basis_points": scorecard.score_basis_points,
                "finding_count": len(scorecard.findings),
                "question_count": len(scorecard.questions),
                "page_count": len(pages),
                "exact_host": config.get("exact_host"),
            }
            job.completed_at = datetime.now(UTC)
            config["last_job_id"] = str(job.id)
            source.config = {**dict(source.config), "service_visibility": config}
            source.status = "ready"
            session.add(
                AuditEvent(
                    workspace_id=source.workspace_id,
                    actor_user_id=None,
                    event_type="service_visibility.run_completed",
                    entity_type="ingestion_job",
                    entity_id=job.id,
                    payload=dict(job.checkpoint),
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            failed_job = await session.get(IngestionJob, job_id)
            failed_source = await session.get(CatalogSource, job.catalog_source_id)
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.completed_at = datetime.now(UTC)
                failed_job.checkpoint = {"error_type": type(exc).__name__}
            if failed_source is not None:
                failed_source.status = "error"
                session.add(
                    AuditEvent(
                        workspace_id=failed_source.workspace_id,
                        actor_user_id=None,
                        event_type="service_visibility.run_failed",
                        entity_type="ingestion_job",
                        entity_id=job_id,
                        payload={"error_type": type(exc).__name__},
                    )
                )
            await session.commit()
