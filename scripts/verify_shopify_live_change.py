from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_PRODUCTS = 1_000
EXPECTED_VARIANTS = 2_000
EXPECTED_SHOP = "northstar-living-demo.myshopify.com"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> bytes:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def _json_optional_object(payload: bytes, *, label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return valid JSON") from exc
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def _workspace_id(login: dict[str, Any]) -> str:
    configured = os.getenv("CATORA_SMOKE_WORKSPACE_ID", "").strip()
    if configured:
        return configured
    user = login.get("user")
    memberships = user.get("memberships") if isinstance(user, dict) else None
    if not isinstance(memberships, list):
        raise RuntimeError("Login response is missing workspace memberships")
    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        if membership.get("workspace_name") == "Northstar Living — Sales Demo":
            workspace_id = membership.get("workspace_id")
            if isinstance(workspace_id, str):
                return workspace_id
    raise RuntimeError("The Northstar sales-demo workspace was not found")


def _datetime(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def evaluate_live_change(
    webhook: dict[str, Any] | None,
    installation: dict[str, Any],
    *,
    not_before: datetime,
) -> tuple[bool, str, dict[str, object] | None]:
    if webhook is None:
        return False, "No verified Shopify webhook has been received yet", None
    if webhook.get("topic") != "products/update":
        return False, f"Latest webhook topic is {webhook.get('topic')}", None
    if webhook.get("signature_verified") is not True:
        return False, "Latest product-update webhook is not signature verified", None
    if webhook.get("status") != "completed":
        return False, f"Latest product-update webhook is {webhook.get('status')}", None
    if not webhook.get("ingestion_job_id"):
        return False, "Latest product-update webhook has no incremental ingestion job", None
    try:
        received_at = _datetime(webhook.get("received_at"), label="Webhook received_at")
        processed_at = _datetime(webhook.get("processed_at"), label="Webhook processed_at")
    except ValueError as exc:
        return False, str(exc), None
    if received_at < not_before:
        return False, "Latest product-update webhook predates this live-change test", None
    if processed_at < received_at:
        return False, "Webhook processed_at predates received_at", None

    if installation.get("shop_domain") != EXPECTED_SHOP:
        return False, "Catora is connected to a different Shopify store", None
    if installation.get("status") != "active" or installation.get("health") != "healthy":
        return False, "Shopify installation is not active and healthy", None
    if set(installation.get("granted_scopes") or []) != {"read_products"}:
        return False, "Shopify installation does not have exactly read_products", None
    if installation.get("sync_status") != "completed":
        return False, f"Incremental synchronization is {installation.get('sync_status')}", None
    if installation.get("product_count") != EXPECTED_PRODUCTS:
        return False, "Reconciled Shopify product total is not 1,000", None
    if installation.get("variant_count") != EXPECTED_VARIANTS:
        return False, "Reconciled Shopify variant total is not 2,000", None
    if not installation.get("last_audit_run_id"):
        return False, "Incremental synchronization has no resulting audit run", None
    try:
        synced_at = _datetime(
            installation.get("last_successful_sync_at"),
            label="Installation last_successful_sync_at",
        )
    except ValueError as exc:
        return False, str(exc), None
    if synced_at < received_at:
        return False, "Catora has not completed a sync after the product-update webhook", None

    return (
        True,
        "Verified product-update webhook and incremental analysis completed",
        {
            "shop_domain": EXPECTED_SHOP,
            "topic": "products/update",
            "signature_verified": True,
            "webhook_status": "completed",
            "received_at": received_at.isoformat(),
            "processed_at": processed_at.isoformat(),
            "incremental_sync_completed_at": synced_at.isoformat(),
            "product_count": EXPECTED_PRODUCTS,
            "variant_count": EXPECTED_VARIANTS,
            "product_id": webhook.get("product_id"),
            "ingestion_job_id": webhook.get("ingestion_job_id"),
            "audit_run_id": installation.get("last_audit_run_id"),
        },
    )


def _write_report(report: dict[str, object]) -> None:
    path_value = os.getenv("CATORA_SHOPIFY_CHANGE_REPORT_PATH", "").strip()
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    api_url = _required("CATORA_SMOKE_API_URL").rstrip("/")
    email = _required("CATORA_SMOKE_EMAIL")
    password = _required("CATORA_SMOKE_PASSWORD")
    timeout_seconds = int(os.getenv("CATORA_SHOPIFY_CHANGE_TIMEOUT_SECONDS", "300"))
    if timeout_seconds < 30 or timeout_seconds > 1_800:
        raise RuntimeError("CATORA_SHOPIFY_CHANGE_TIMEOUT_SECONDS must be between 30 and 1800")
    configured_not_before = os.getenv("CATORA_SHOPIFY_CHANGE_NOT_BEFORE", "").strip()
    not_before = (
        _datetime(configured_not_before, label="CATORA_SHOPIFY_CHANGE_NOT_BEFORE")
        if configured_not_before
        else datetime.now(UTC)
    )

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    login = _json_object(
        _request(
            opener,
            f"{api_url}/api/v1/auth/login",
            method="POST",
            payload={"email": email, "password": password},
        ),
        label="Login",
    )
    workspace_id = _workspace_id(login)
    deadline = time.monotonic() + timeout_seconds
    last_reason = "Waiting for Shopify product update"

    print(
        "Watching for a new verified Shopify products/update webhook. "
        "Make the controlled Cloudline width change now."
    )
    while time.monotonic() < deadline:
        webhook = _json_optional_object(
            _request(
                opener,
                f"{api_url}/api/v1/workspaces/{workspace_id}/shopify/webhooks/latest",
            ),
            label="Latest Shopify webhook",
        )
        installation = _json_object(
            _request(
                opener,
                f"{api_url}/api/v1/workspaces/{workspace_id}/shopify/installation",
            ),
            label="Shopify installation",
        )
        complete, reason, summary = evaluate_live_change(
            webhook,
            installation,
            not_before=not_before,
        )
        if complete and summary is not None:
            report = {
                "status": "passed",
                "workspace_id": workspace_id,
                "not_before": not_before.isoformat(),
                **summary,
            }
            _write_report(report)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        last_reason = reason
        time.sleep(5)

    raise RuntimeError(
        f"Live Shopify change did not complete within {timeout_seconds} seconds: {last_reason}"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Shopify live-change verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
