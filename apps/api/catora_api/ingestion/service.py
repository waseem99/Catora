from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.connectors.base import CatalogConnector, ConnectorPage, ConnectorRejection
from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord

CancellationCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    job_id: uuid.UUID
    status: str
    processed_count: int
    success_count: int
    rejection_count: int
    warning_count: int
    duplicate_count: int


class IngestionScopeError(ValueError):
    pass


class IngestionService:
    def __init__(self, *, page_size: int = 250, rejection_sample_limit: int = 100) -> None:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if rejection_sample_limit < 0:
            raise ValueError("rejection_sample_limit cannot be negative")
        self.page_size = page_size
        self.rejection_sample_limit = rejection_sample_limit

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    async def run(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
        connector: CatalogConnector,
        should_cancel: CancellationCheck | None = None,
    ) -> IngestionSummary:
        self._validate_scope(source, job, connector)
        if job.status == "cancelled":
            return self._summary(job)

        job.status = "validating"
        job.started_at = job.started_at or self.now()
        await session.commit()

        try:
            validation = await connector.validate()
        except Exception as exc:
            await self._record_failure(session, job, exc)
            raise
        job.warning_count += len(validation.warnings)
        if not validation.valid:
            job.status = "failed"
            job.completed_at = self.now()
            job.checkpoint = self._merge_checkpoint(
                job.checkpoint,
                validation_errors=list(validation.errors),
                validation_warnings=list(validation.warnings),
            )
            await session.commit()
            return self._summary(job)

        job.status = "running"
        job.checkpoint = self._merge_checkpoint(
            job.checkpoint,
            validation_errors=[],
            validation_warnings=list(validation.warnings),
        )
        await session.commit()

        connector_checkpoint = self._connector_checkpoint(job.checkpoint)
        duplicate_count = self._checkpoint_int(job.checkpoint, "duplicate_count")
        rejection_samples = self._rejection_samples(job.checkpoint)

        try:
            async for page in connector.pages(
                checkpoint=connector_checkpoint,
                page_size=self.page_size,
            ):
                if job.status == "cancelled" or (
                    should_cancel is not None and await should_cancel()
                ):
                    job.status = "cancelled"
                    job.completed_at = self.now()
                    await session.commit()
                    return self._summary(job, duplicate_count=duplicate_count)

                inserted_count = await self._persist_page(session, source=source, job=job, page=page)
                duplicate_count += len(page.records) - inserted_count
                job.processed_count += len(page.records) + len(page.rejections)
                job.success_count += len(page.records)
                job.rejection_count += len(page.rejections)
                job.warning_count += sum(len(record.warnings) for record in page.records)
                rejection_samples = self._append_rejections(rejection_samples, page.rejections)
                connector_checkpoint = page.next_checkpoint
                job.checkpoint = self._merge_checkpoint(
                    job.checkpoint,
                    connector=dict(connector_checkpoint or {}),
                    duplicate_count=duplicate_count,
                    rejection_samples=rejection_samples,
                )
                await session.commit()
        except Exception as exc:
            await self._record_failure(
                session,
                job,
                exc,
                duplicate_count=duplicate_count,
                rejection_samples=rejection_samples,
            )
            raise

        job.status = "partially_completed" if job.rejection_count else "completed"
        job.completed_at = self.now()
        job.checkpoint = self._merge_checkpoint(
            job.checkpoint,
            connector=dict(connector_checkpoint or {}),
            duplicate_count=duplicate_count,
            rejection_samples=rejection_samples,
        )
        source.status = "active" if job.status in {"completed", "partially_completed"} else source.status
        await session.commit()
        return self._summary(job, duplicate_count=duplicate_count)

    async def _record_failure(
        self,
        session: AsyncSession,
        job: IngestionJob,
        exc: Exception,
        *,
        duplicate_count: int | None = None,
        rejection_samples: list[dict[str, Any]] | None = None,
    ) -> None:
        job_id = job.id
        checkpoint_snapshot = dict(job.checkpoint)
        await session.rollback()
        persisted_job = await session.get(IngestionJob, job_id)
        if persisted_job is None:
            raise RuntimeError("Ingestion job disappeared while recording failure") from exc
        updates: dict[str, object] = {
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
        if duplicate_count is not None:
            updates["duplicate_count"] = duplicate_count
        if rejection_samples is not None:
            updates["rejection_samples"] = rejection_samples
        persisted_job.status = "failed"
        persisted_job.completed_at = self.now()
        persisted_job.checkpoint = self._merge_checkpoint(checkpoint_snapshot, **updates)
        await session.commit()

    async def _persist_page(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
        page: ConnectorPage,
    ) -> int:
        if not page.records:
            return 0
        keys = [(record.external_id, record.content_hash) for record in page.records]
        existing_rows = (
            await session.execute(
                select(SourceRecord.external_id, SourceRecord.content_hash).where(
                    SourceRecord.catalog_source_id == source.id,
                    tuple_(SourceRecord.external_id, SourceRecord.content_hash).in_(keys),
                )
            )
        ).all()
        existing = {(external_id, content_hash) for external_id, content_hash in existing_rows}
        new_records = [
            SourceRecord(
                workspace_id=source.workspace_id,
                catalog_source_id=source.id,
                ingestion_job_id=job.id,
                external_id=record.external_id,
                record_type=record.record_type,
                payload=dict(record.payload),
                content_hash=record.content_hash,
                source_updated_at=record.source_updated_at,
            )
            for record in page.records
            if (record.external_id, record.content_hash) not in existing
        ]
        session.add_all(new_records)
        await session.flush()
        return len(new_records)

    def _append_rejections(
        self,
        current: list[dict[str, Any]],
        additions: tuple[ConnectorRejection, ...],
    ) -> list[dict[str, Any]]:
        if self.rejection_sample_limit == 0:
            return []
        combined = [
            *current,
            *[
                {
                    "row_number": item.row_number,
                    "reason": item.reason,
                    "raw_payload": dict(item.raw_payload),
                }
                for item in additions
            ],
        ]
        return combined[-self.rejection_sample_limit :]

    @staticmethod
    def _validate_scope(
        source: CatalogSource, job: IngestionJob, connector: CatalogConnector
    ) -> None:
        if source.workspace_id != job.workspace_id:
            raise IngestionScopeError("Source and job belong to different workspaces")
        if source.id != job.catalog_source_id:
            raise IngestionScopeError("Job does not belong to the supplied source")
        if source.source_type != connector.source_type:
            raise IngestionScopeError("Connector type does not match catalog source")

    @staticmethod
    def _connector_checkpoint(checkpoint: Mapping[str, object]) -> Mapping[str, Any] | None:
        value = checkpoint.get("connector")
        return value if isinstance(value, dict) else None

    @staticmethod
    def _checkpoint_int(checkpoint: Mapping[str, object], key: str) -> int:
        value = checkpoint.get(key, 0)
        return value if isinstance(value, int) and value >= 0 else 0

    @staticmethod
    def _rejection_samples(checkpoint: Mapping[str, object]) -> list[dict[str, Any]]:
        value = checkpoint.get("rejection_samples")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _merge_checkpoint(
        checkpoint: Mapping[str, object], **updates: object
    ) -> dict[str, object]:
        return {**dict(checkpoint), **updates}

    @staticmethod
    def _summary(job: IngestionJob, *, duplicate_count: int | None = None) -> IngestionSummary:
        if duplicate_count is None:
            duplicate_count = IngestionService._checkpoint_int(job.checkpoint, "duplicate_count")
        return IngestionSummary(
            job_id=job.id,
            status=job.status,
            processed_count=job.processed_count,
            success_count=job.success_count,
            rejection_count=job.rejection_count,
            warning_count=job.warning_count,
            duplicate_count=duplicate_count,
        )
