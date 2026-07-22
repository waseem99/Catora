from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

import catora_api.api.intent_suite_reruns as rerun_api
from catora_api.db.models.intents import IntentSuite, IntentSuiteRun
from catora_api.db.models.reporting import AuditEvent
from catora_api.intents.suite_reruns import (
    IntentSuiteHistoryRerunConflictError,
    IntentSuiteHistoryRerunNotFoundError,
    IntentSuiteHistoryRerunService,
    PersistedIntentSuiteHistoryRerun,
    _validated_source,
)
from catora_api.intents.suites import (
    IntentSuiteRunSummary,
    PersistedIntentSuiteRun,
)
from catora_api.schemas.intent_suite_reruns import IntentSuiteHistoryRerunRequest


class FakeSession:
    def __init__(self, source_run: IntentSuiteRun | None) -> None:
        self.source_run = source_run
        self.added: list[object] = []
        self.commit_count = 0
        self.refreshed: list[object] = []

    async def scalar(self, _statement: object) -> IntentSuiteRun | None:
        return self.source_run

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


class FakeSuiteService:
    def __init__(self, persisted: PersistedIntentSuiteRun) -> None:
        self.persisted = persisted
        self.calls: list[dict[str, object]] = []

    async def execute(self, _session: object, **kwargs: object) -> PersistedIntentSuiteRun:
        self.calls.append(kwargs)
        return self.persisted


class FakeAuthService:
    async def membership(
        self,
        _session: object,
        _user_id: uuid.UUID,
        _workspace_id: uuid.UUID,
    ) -> SimpleNamespace:
        return SimpleNamespace(role="analyst")


class FakeRerunService:
    def __init__(self, result: PersistedIntentSuiteHistoryRerun) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def rerun(self, _session: object, **kwargs: object) -> PersistedIntentSuiteHistoryRerun:
        self.calls.append(kwargs)
        return self.result


def _source_run(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    product_ids: list[str],
    status: str = "completed",
    snapshot_hash: str | None = None,
) -> IntentSuiteRun:
    now = datetime.now(UTC)
    return IntentSuiteRun(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        previous_run_id=None,
        status=status,
        requested_product_ids=product_ids,
        source_snapshot_hash=snapshot_hash or "a" * 64,
        started_at=now,
        completed_at=now if status == "completed" else None,
        created_at=now,
        updated_at=now,
    )


def _persisted_run(
    *,
    workspace_id: uuid.UUID,
    suite_id: uuid.UUID,
    product_ids: tuple[uuid.UUID, ...],
) -> PersistedIntentSuiteRun:
    now = datetime.now(UTC)
    suite = IntentSuite(
        id=suite_id,
        workspace_id=workspace_id,
        name="Furniture coverage",
        description=None,
        created_at=now,
        updated_at=now,
    )
    run = IntentSuiteRun(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        intent_suite_id=suite_id,
        previous_run_id=uuid.uuid4(),
        status="completed",
        requested_product_ids=[str(item) for item in product_ids],
        source_snapshot_hash="b" * 64,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    summary = IntentSuiteRunSummary(
        member_count=2,
        intent_run_count=2,
        target_count=8,
        product_count=4,
        confident_match_count=5,
        possible_match_missing_data_count=1,
        non_match_count=1,
        insufficient_category_data_count=1,
        confident_coverage_basis_points=6250,
    )
    return PersistedIntentSuiteRun(
        run=run,
        suite=suite,
        child_runs=(),
        child_run_ids=(uuid.uuid4(), uuid.uuid4()),
        summary=summary,
        delta=None,
    )


@pytest.mark.asyncio
async def test_rerun_reuses_exact_canonical_product_selection() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    product_ids = tuple(sorted((uuid.uuid4(), uuid.uuid4()), key=str))
    source = _source_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=[str(item) for item in product_ids],
    )
    persisted = _persisted_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=product_ids,
    )
    suite_service = FakeSuiteService(persisted)
    service = IntentSuiteHistoryRerunService(cast(Any, suite_service))

    result = await service.rerun(
        cast(Any, FakeSession(source)),
        workspace_id=workspace_id,
        source_run_id=source.id,
        expected_source_snapshot_hash="a" * 64,
    )

    assert result.source_run is source
    assert result.product_ids == product_ids
    assert result.selection_mode == "explicit"
    assert suite_service.calls == [
        {
            "workspace_id": workspace_id,
            "suite_id": suite_id,
            "product_ids": product_ids,
        }
    ]


@pytest.mark.asyncio
async def test_rerun_rejects_stale_snapshot_before_execution() -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    source = _source_run(workspace_id=workspace_id, suite_id=suite_id, product_ids=[])
    suite_service = FakeSuiteService(
        _persisted_run(workspace_id=workspace_id, suite_id=suite_id, product_ids=())
    )
    service = IntentSuiteHistoryRerunService(cast(Any, suite_service))

    with pytest.raises(IntentSuiteHistoryRerunConflictError, match="snapshot changed"):
        await service.rerun(
            cast(Any, FakeSession(source)),
            workspace_id=workspace_id,
            source_run_id=source.id,
            expected_source_snapshot_hash="c" * 64,
        )

    assert suite_service.calls == []


@pytest.mark.asyncio
async def test_rerun_hides_missing_cross_tenant_source() -> None:
    service = IntentSuiteHistoryRerunService()
    with pytest.raises(IntentSuiteHistoryRerunNotFoundError, match="not found"):
        await service.rerun(
            cast(Any, FakeSession(None)),
            workspace_id=uuid.uuid4(),
            source_run_id=uuid.uuid4(),
            expected_source_snapshot_hash="a" * 64,
        )


@pytest.mark.parametrize(
    ("product_ids", "status", "message"),
    [
        (["not-a-uuid"], "completed", "selection is invalid"),
        ([str(uuid.UUID(int=1)), str(uuid.UUID(int=1))], "completed", "duplicates"),
        ([str(uuid.UUID(int=2)), str(uuid.UUID(int=1))], "completed", "ordered"),
        ([], "running", "Only a completed"),
    ],
)
def test_source_validation_fails_closed(
    product_ids: list[str],
    status: str,
    message: str,
) -> None:
    source = _source_run(
        workspace_id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
        product_ids=product_ids,
        status=status,
    )
    with pytest.raises(IntentSuiteHistoryRerunConflictError, match=message):
        _validated_source(source)


@pytest.mark.asyncio
async def test_rerun_endpoint_records_source_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    user_id = uuid.uuid4()
    product_ids = (uuid.uuid4(),)
    source = _source_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=[str(product_ids[0])],
    )
    persisted = _persisted_run(
        workspace_id=workspace_id,
        suite_id=suite_id,
        product_ids=product_ids,
    )
    result = PersistedIntentSuiteHistoryRerun(
        source_run=source,
        source_snapshot_hash="a" * 64,
        product_ids=product_ids,
        persisted=persisted,
    )
    rerun_service = FakeRerunService(result)
    monkeypatch.setattr(rerun_api, "rerun_service", rerun_service)
    session = FakeSession(source)

    response = await rerun_api.rerun_intent_suite_from_history(
        workspace_id=workspace_id,
        source_run_id=source.id,
        payload=IntentSuiteHistoryRerunRequest(
            expected_source_snapshot_hash="a" * 64
        ),
        session=cast(Any, session),
        auth_service=cast(Any, FakeAuthService()),
        context=cast(Any, SimpleNamespace(user=SimpleNamespace(id=user_id))),
    )

    assert response.source_run_id == source.id
    assert response.reused_product_ids == product_ids
    assert response.run.id == persisted.run.id
    assert session.commit_count == 1
    assert session.refreshed == [persisted.run]
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert audit.event_type == "intent_suite.rerun_completed"
    assert audit.actor_user_id == user_id
    assert audit.payload["source_run_id"] == str(source.id)
    assert audit.payload["source_snapshot_hash"] == "a" * 64
    assert audit.payload["reused_product_count"] == 1


def test_rerun_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = (
        "/api/v1/workspaces/{workspace_id}/intent-suite-runs/"
        "{source_run_id}/rerun"
    )
    operation = app.openapi()["paths"][path]["post"]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/IntentSuiteHistoryRerunView")
