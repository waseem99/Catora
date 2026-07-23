from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.verify_shopify_live_change import evaluate_live_change


def _webhook(received_at: datetime) -> dict[str, object]:
    return {
        "topic": "products/update",
        "status": "completed",
        "signature_verified": True,
        "received_at": received_at.isoformat(),
        "processed_at": (received_at + timedelta(seconds=2)).isoformat(),
        "product_id": "1234567890",
        "ingestion_job_id": "7b1608dc-69ff-44d2-a014-08d09be8dbe9",
    }


def _installation(synced_at: datetime) -> dict[str, object]:
    return {
        "shop_domain": "northstar-living-demo.myshopify.com",
        "status": "active",
        "health": "healthy",
        "granted_scopes": ["read_products"],
        "sync_status": "completed",
        "last_successful_sync_at": synced_at.isoformat(),
        "last_audit_run_id": "6a453aa8-52ed-49e0-bb8f-307460a7beb4",
        "product_count": 1_000,
        "variant_count": 2_000,
    }


def test_live_change_passes_after_verified_webhook_and_followup_sync() -> None:
    not_before = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    received_at = not_before + timedelta(seconds=10)

    complete, reason, summary = evaluate_live_change(
        _webhook(received_at),
        _installation(received_at + timedelta(seconds=20)),
        not_before=not_before,
    )

    assert complete is True
    assert "completed" in reason
    assert summary is not None
    assert summary["product_count"] == 1_000
    assert summary["variant_count"] == 2_000


def test_live_change_rejects_a_delivery_from_before_the_test() -> None:
    not_before = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    received_at = not_before - timedelta(seconds=1)

    complete, reason, summary = evaluate_live_change(
        _webhook(received_at),
        _installation(not_before + timedelta(seconds=20)),
        not_before=not_before,
    )

    assert complete is False
    assert "predates" in reason
    assert summary is None


def test_live_change_waits_for_sync_after_webhook() -> None:
    not_before = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    received_at = not_before + timedelta(seconds=10)

    complete, reason, summary = evaluate_live_change(
        _webhook(received_at),
        _installation(received_at - timedelta(seconds=1)),
        not_before=not_before,
    )

    assert complete is False
    assert "has not completed a sync" in reason
    assert summary is None


def test_live_change_rejects_write_scope_expansion() -> None:
    not_before = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    received_at = not_before + timedelta(seconds=10)
    installation = _installation(received_at + timedelta(seconds=20))
    installation["granted_scopes"] = ["read_products", "write_products"]

    complete, reason, summary = evaluate_live_change(
        _webhook(received_at),
        installation,
        not_before=not_before,
    )

    assert complete is False
    assert "exactly read_products" in reason
    assert summary is None
