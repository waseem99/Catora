from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from catora_api.auth.roles import Role, can
from catora_api.demo import reliability
from catora_api.main import app
from catora_api.schemas.demo import DemoPreflightResponse, DemoResetRequest


def test_presenter_capability_is_limited_to_owner_and_admin() -> None:
    assert can(Role.OWNER, "demo.present")
    assert can(Role.ADMIN, "demo.present")
    assert not can(Role.ANALYST, "demo.present")
    assert not can(Role.REVIEWER, "demo.present")
    assert not can(Role.VIEWER, "demo.present")


def test_preflight_contract_preserves_last_verified_snapshot() -> None:
    now = datetime.now(UTC)
    response = DemoPreflightResponse.model_validate(
        {
            "workspace_id": uuid.uuid4(),
            "generated_at": now,
            "ready": False,
            "components": [
                {
                    "key": "worker",
                    "label": "Background worker",
                    "state": "warning",
                    "detail": "Unavailable (RuntimeError)",
                }
            ],
            "last_verified_snapshot": {
                "audit_run_id": uuid.uuid4(),
                "source_snapshot_hash": "a" * 64,
                "verified_at": now,
                "product_count": 1_000,
                "variant_count": 2_000,
                "finding_count": 387,
                "recommendation_field_count": 3,
            },
        }
    )
    assert response.last_verified_snapshot.product_count == 1_000
    assert response.components[0].state == "warning"


def test_reset_request_requires_a_meaningful_reason() -> None:
    request = DemoResetRequest(reason="Prepare the workspace for a client presentation")
    assert request.reason.startswith("Prepare")


def test_reset_status_never_exposes_celery_failure_details(monkeypatch: object) -> None:
    class FakeResult:
        state = "FAILURE"

    monkeypatch.setattr(  # type: ignore[attr-defined]
        reliability,
        "AsyncResult",
        lambda *_args, **_kwargs: FakeResult(),
    )
    response = reliability.demo_reset_status(uuid.uuid4())
    assert response.status == "failed"
    assert "previous verified snapshot" in response.detail


def test_reset_enqueue_uses_the_recorded_task_identity(monkeypatch: object) -> None:
    task_id = uuid.uuid4()
    captured: dict[str, object] = {}

    class FakeTask:
        def apply_async(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(id=task_id)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        __import__("catora_api.demo.tasks", fromlist=["reset_sales_demo"]),
        "reset_sales_demo",
        FakeTask(),
    )
    reliability.enqueue_demo_reset(
        task_id=task_id,
        actor_user_id=uuid.uuid4(),
        reason="Reset before a client meeting",
    )
    assert captured["task_id"] == str(task_id)


def test_presenter_reliability_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/v1/workspaces/{workspace_id}/demo/preflight" in paths
    assert "/api/v1/workspaces/{workspace_id}/demo/reset" in paths
    assert "/api/v1/workspaces/{workspace_id}/demo/reset/{task_id}" in paths
