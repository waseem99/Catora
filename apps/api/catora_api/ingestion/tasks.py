from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.db.models.catalog import CatalogSource, IngestionJob
from catora_api.ingestion.factory import connector_for_source
from catora_api.ingestion.service import IngestionService
from catora_api.storage import ObjectStorage


@shared_task(name="catora.ingestion.run", ignore_result=True)  # type: ignore[misc]
def run_ingestion_job(job_id: str) -> None:
    asyncio.run(_run_ingestion_job(uuid.UUID(job_id)))


async def _run_ingestion_job(job_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None or job.status == "cancelled":
            return
        source = await session.get(CatalogSource, job.catalog_source_id)
        if source is None:
            job.status = "failed"
            job.checkpoint = {
                "error_type": "MissingSource",
                "error_message": "Catalog source not found",
            }
            await session.commit()
            return

        try:
            connector = await connector_for_source(source, ObjectStorage(get_settings()))
        except Exception as exc:
            job.status = "failed"
            job.checkpoint = {
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }
            await session.commit()
            raise

        async def should_cancel() -> bool:
            await session.refresh(job, attribute_names=["status"])
            return job.status == "cancelled"

        await IngestionService().run(
            session,
            source=source,
            job=job,
            connector=connector,
            should_cancel=should_cancel,
        )
