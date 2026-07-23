from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models.identity import Workspace
from catora_api.db.models.reporting import AuditEvent
from catora_api.demo.reliability import DEMO_WORKSPACE_SLUG
from catora_api.worker import celery_app


async def _record_reset_event(
    *,
    actor_user_id: uuid.UUID,
    event_type: str,
    task_id: str,
    reason: str,
    detail: str,
) -> None:
    async with SessionFactory() as session:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG)
        )
        if workspace is None:
            return
        session.add(
            AuditEvent(
                workspace_id=workspace.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type="workspace",
                entity_id=workspace.id,
                payload={
                    "task_id": task_id,
                    "reason": reason,
                    "detail": detail,
                },
            )
        )
        await session.commit()


@celery_app.task(bind=True, name="catora.demo.reset_sales_demo")  # type: ignore[misc]
def reset_sales_demo(
    self: Any,
    *,
    actor_user_id: str,
    reason: str,
) -> dict[str, str]:
    task_id = str(self.request.id)
    actor_id = uuid.UUID(actor_user_id)
    api_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "scripts/seed_enterprise_demo.py"]
    try:
        completed = subprocess.run(
            command,
            cwd=api_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=720,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        asyncio.run(
            _record_reset_event(
                actor_user_id=actor_id,
                event_type="demo.reset_failed",
                task_id=task_id,
                reason=reason,
                detail=type(exc).__name__,
            )
        )
        raise RuntimeError("The deterministic demo reset could not be executed") from exc

    if completed.returncode != 0:
        asyncio.run(
            _record_reset_event(
                actor_user_id=actor_id,
                event_type="demo.reset_failed",
                task_id=task_id,
                reason=reason,
                detail=f"seed_exit_{completed.returncode}",
            )
        )
        raise RuntimeError("The deterministic demo reset failed")

    asyncio.run(
        _record_reset_event(
            actor_user_id=actor_id,
            event_type="demo.reset_completed",
            task_id=task_id,
            reason=reason,
            detail="enterprise_showcase_recreated",
        )
    )
    return {"status": "completed", "task_id": task_id}
