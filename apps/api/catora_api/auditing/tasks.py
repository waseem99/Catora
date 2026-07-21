from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from catora_api.auditing.stateful_service import StatefulAuditRunService
from catora_api.database import SessionFactory


@shared_task(name="catora.audit.run", ignore_result=True)  # type: ignore[misc]
def run_audit(run_id: str) -> None:
    asyncio.run(_run_audit(uuid.UUID(run_id)))


async def _run_audit(run_id: uuid.UUID) -> None:
    async with SessionFactory() as session:
        await StatefulAuditRunService().execute_run(session, run_id=run_id)
