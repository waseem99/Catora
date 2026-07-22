from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.intents import IntentSuiteRun
from catora_api.intents.suites import IntentSuiteService, PersistedIntentSuiteRun

_SNAPSHOT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_PRODUCT_SELECTION = 10_000


class IntentSuiteHistoryRerunError(RuntimeError):
    pass


class IntentSuiteHistoryRerunNotFoundError(IntentSuiteHistoryRerunError):
    pass


class IntentSuiteHistoryRerunConflictError(IntentSuiteHistoryRerunError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedIntentSuiteHistoryRerun:
    source_run: IntentSuiteRun
    source_snapshot_hash: str
    product_ids: tuple[uuid.UUID, ...]
    persisted: PersistedIntentSuiteRun

    @property
    def selection_mode(self) -> Literal["all_active", "explicit"]:
        return "explicit" if self.product_ids else "all_active"


class IntentSuiteHistoryRerunService:
    def __init__(self, suite_service: IntentSuiteService | None = None) -> None:
        self.suite_service = suite_service or IntentSuiteService()

    async def rerun(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        source_run_id: uuid.UUID,
        expected_source_snapshot_hash: str,
    ) -> PersistedIntentSuiteHistoryRerun:
        source_run = await session.scalar(
            select(IntentSuiteRun).where(
                IntentSuiteRun.id == source_run_id,
                IntentSuiteRun.workspace_id == workspace_id,
            )
        )
        if source_run is None:
            raise IntentSuiteHistoryRerunNotFoundError("Intent suite run not found")

        source_snapshot_hash, product_ids = _validated_source(source_run)
        if not secrets.compare_digest(
            expected_source_snapshot_hash,
            source_snapshot_hash,
        ):
            raise IntentSuiteHistoryRerunConflictError(
                "Intent suite source snapshot changed; reload the historical run"
            )

        persisted = await self.suite_service.execute(
            session,
            workspace_id=workspace_id,
            suite_id=source_run.intent_suite_id,
            product_ids=product_ids,
        )
        return PersistedIntentSuiteHistoryRerun(
            source_run=source_run,
            source_snapshot_hash=source_snapshot_hash,
            product_ids=product_ids,
            persisted=persisted,
        )


def _validated_source(run: IntentSuiteRun) -> tuple[str, tuple[uuid.UUID, ...]]:
    if run.status != "completed":
        raise IntentSuiteHistoryRerunConflictError(
            "Only a completed intent suite run can be used as a rerun source"
        )
    if run.started_at is None or run.completed_at is None:
        raise IntentSuiteHistoryRerunConflictError(
            "Completed intent suite run timestamps are incomplete"
        )

    snapshot_hash = run.source_snapshot_hash
    if snapshot_hash is None or _SNAPSHOT_PATTERN.fullmatch(snapshot_hash) is None:
        raise IntentSuiteHistoryRerunConflictError(
            "Completed intent suite run snapshot is invalid"
        )

    raw_product_ids: object = run.requested_product_ids
    if not isinstance(raw_product_ids, list):
        raise IntentSuiteHistoryRerunConflictError(
            "Intent suite run product selection is invalid"
        )
    if len(raw_product_ids) > _MAX_PRODUCT_SELECTION:
        raise IntentSuiteHistoryRerunConflictError(
            "Intent suite run product selection exceeds the supported limit"
        )

    parsed: list[uuid.UUID] = []
    canonical: list[str] = []
    for value in raw_product_ids:
        if not isinstance(value, str):
            raise IntentSuiteHistoryRerunConflictError(
                "Intent suite run product selection is invalid"
            )
        try:
            product_id = uuid.UUID(value)
        except ValueError as exc:
            raise IntentSuiteHistoryRerunConflictError(
                "Intent suite run product selection is invalid"
            ) from exc
        if str(product_id) != value:
            raise IntentSuiteHistoryRerunConflictError(
                "Intent suite run product selection is not canonical"
            )
        parsed.append(product_id)
        canonical.append(value)

    if len(canonical) != len(set(canonical)):
        raise IntentSuiteHistoryRerunConflictError(
            "Intent suite run product selection contains duplicates"
        )
    if canonical != sorted(canonical):
        raise IntentSuiteHistoryRerunConflictError(
            "Intent suite run product selection is not canonically ordered"
        )
    return snapshot_hash, tuple(parsed)
