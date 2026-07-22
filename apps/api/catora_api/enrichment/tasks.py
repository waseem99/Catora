from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from catora_api.config import get_settings
from catora_api.database import SessionFactory
from catora_api.enrichment.jobs import RecommendationJobService


@shared_task(name="catora.recommendation.run", ignore_result=True)  # type: ignore[misc]
def run_recommendation_job(job_id: str) -> None:
    asyncio.run(_run_recommendation_job(uuid.UUID(job_id)))


async def _run_recommendation_job(job_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        await RecommendationJobService().execute(
            session,
            job_id=job_id,
            settings=get_settings(),
        )
