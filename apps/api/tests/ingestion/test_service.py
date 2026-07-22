from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from catora_api.connectors.base import (
    CatalogConnector,
    ConnectorCapabilities,
    ConnectorPage,
    ConnectorRecord,
    ConnectorRejection,
    ConnectorValidation,
)
from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.ingestion.service import IngestionScopeError, IngestionService


class FakeResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class FakeSession:
    def __init__(self) -> None:
        self.existing: set[tuple[str, str]] = set()
        self.added: list[SourceRecord] = []
        self.commits = 0
        self.rollbacks = 0
        self.job: IngestionJob | None = None

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(list(self.existing))

    def add_all(self, records: list[SourceRecord]) -> None:
        self.added.extend(records)
        self.existing.update((record.external_id, record.content_hash) for record in records)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def get(
        self, _model: type[IngestionJob], _object_id: uuid.UUID
    ) -> IngestionJob | None:
        return self.job


class FailingValidationConnector(CatalogConnector):
    source_type = "csv"
    capabilities = ConnectorCapabilities()

    async def validate(self) -> ConnectorValidation:
        raise RuntimeError("validation failure")

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        del checkpoint, page_size
        if False:
            yield ConnectorPage((), (), None)


class FailingConnector(CatalogConnector):
    source_type = "csv"
    capabilities = ConnectorCapabilities()

    async def validate(self) -> ConnectorValidation:
        return ConnectorValidation(valid=True)

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        del checkpoint, page_size
        raise RuntimeError("connector failure")
        yield  # pragma: no cover


class StubConnector(CatalogConnector):
    source_type = "csv"
    capabilities = ConnectorCapabilities()

    def __init__(
        self,
        pages: list[ConnectorPage],
        validation: ConnectorValidation | None = None,
    ) -> None:
        self._pages = pages
        self._validation = validation or ConnectorValidation(valid=True)

    async def validate(self) -> ConnectorValidation:
        return self._validation

    async def pages(
        self,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[ConnectorPage]:
        del page_size
        start = int((checkpoint or {}).get("page", 0))
        for index, page in enumerate(self._pages[start:], start=start + 1):
            yield ConnectorPage(page.records, page.rejections, {"page": index})


def source_and_job() -> tuple[CatalogSource, IngestionJob]:
    workspace_id = uuid.uuid4()
    source_id = uuid.uuid4()
    source = CatalogSource(
        id=source_id,
        workspace_id=workspace_id,
        name="CSV",
        source_type="csv",
        status="draft",
        config={},
    )
    job = IngestionJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        catalog_source_id=source_id,
        status="queued",
        checkpoint={},
        processed_count=0,
        success_count=0,
        rejection_count=0,
        warning_count=0,
    )
    return source, job


def record(external_id: str, content_hash: str) -> ConnectorRecord:
    return ConnectorRecord(
        external_id=external_id,
        record_type="product",
        payload={"title": external_id},
        content_hash=content_hash,
    )


@pytest.mark.asyncio
async def test_run_persists_records_and_partial_rejections() -> None:
    source, job = source_and_job()
    session = FakeSession()
    connector = StubConnector(
        [
            ConnectorPage(
                (record("p1", "h1"), record("p2", "h2")),
                (ConnectorRejection(3, "bad", {"id": ""}),),
                {"page": 1},
            )
        ]
    )

    summary = await IngestionService(page_size=10).run(
        session,  # type: ignore[arg-type]
        source=source,
        job=job,
        connector=connector,
    )

    assert summary.status == "partially_completed"
    assert summary.processed_count == 3
    assert summary.success_count == 2
    assert summary.rejection_count == 1
    assert len(session.added) == 2
    assert source.status == "active"
    assert job.checkpoint["duplicate_count"] == 0


@pytest.mark.asyncio
async def test_rerun_is_idempotent_and_counts_duplicates() -> None:
    source, job = source_and_job()
    session = FakeSession()
    session.existing = {("p1", "h1")}
    connector = StubConnector(
        [ConnectorPage((record("p1", "h1"), record("p2", "h2")), (), {"page": 1})]
    )

    summary = await IngestionService().run(
        session,  # type: ignore[arg-type]
        source=source,
        job=job,
        connector=connector,
    )

    assert len(session.added) == 1
    assert session.added[0].external_id == "p2"
    assert summary.duplicate_count == 1
    assert summary.success_count == 2


@pytest.mark.asyncio
async def test_validation_failure_is_persisted_without_pages() -> None:
    source, job = source_and_job()
    session = FakeSession()
    connector = StubConnector(
        [],
        ConnectorValidation(
            valid=False,
            errors=("missing title",),
            warnings=("x",),
        ),
    )

    summary = await IngestionService().run(
        session,  # type: ignore[arg-type]
        source=source,
        job=job,
        connector=connector,
    )

    assert summary.status == "failed"
    assert job.checkpoint["validation_errors"] == ["missing title"]
    assert summary.warning_count == 1


@pytest.mark.asyncio
async def test_cancellation_stops_before_persisting_page() -> None:
    source, job = source_and_job()
    session = FakeSession()
    connector = StubConnector([ConnectorPage((record("p1", "h1"),), (), {"page": 1})])

    async def cancelled() -> bool:
        return True

    summary = await IngestionService().run(
        session,  # type: ignore[arg-type]
        source=source,
        job=job,
        connector=connector,
        should_cancel=cancelled,
    )

    assert summary.status == "cancelled"
    assert session.added == []


@pytest.mark.asyncio
async def test_scope_mismatch_is_rejected() -> None:
    source, job = source_and_job()
    job.workspace_id = uuid.uuid4()
    session = FakeSession()

    with pytest.raises(IngestionScopeError):
        await IngestionService().run(
            session,  # type: ignore[arg-type]
            source=source,
            job=job,
            connector=StubConnector([]),
        )


@pytest.mark.asyncio
async def test_connector_failure_is_recorded_after_rollback() -> None:
    source, job = source_and_job()
    session = FakeSession()
    session.job = job

    with pytest.raises(RuntimeError, match="connector failure"):
        await IngestionService().run(
            session,  # type: ignore[arg-type]
            source=source,
            job=job,
            connector=FailingConnector(),
        )

    assert session.rollbacks == 1
    assert job.status == "failed"
    assert job.checkpoint["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_validation_exception_is_recorded_after_rollback() -> None:
    source, job = source_and_job()
    session = FakeSession()
    session.job = job

    with pytest.raises(RuntimeError, match="validation failure"):
        await IngestionService().run(
            session,  # type: ignore[arg-type]
            source=source,
            job=job,
            connector=FailingValidationConnector(),
        )

    assert session.rollbacks == 1
    assert job.status == "failed"
    assert job.checkpoint["error_type"] == "RuntimeError"
