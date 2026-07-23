from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value.rstrip("/")


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc


def _json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return parsed


def _membership_workspace_id(login: dict[str, Any]) -> str:
    configured = os.getenv("CATORA_SMOKE_WORKSPACE_ID", "").strip()
    if configured:
        return configured
    user = login.get("user")
    if not isinstance(user, dict):
        raise RuntimeError("Login response is missing user data")
    memberships = user.get("memberships")
    if not isinstance(memberships, list):
        raise RuntimeError("Login response is missing memberships")
    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        if membership.get("workspace_name") == "Northstar Living — Sales Demo":
            workspace_id = membership.get("workspace_id")
            if isinstance(workspace_id, str):
                return workspace_id
    raise RuntimeError("The demo workspace membership was not found")


def main() -> int:
    api_url = _required("CATORA_SMOKE_API_URL")
    email = _required("CATORA_SMOKE_EMAIL")
    password = _required("CATORA_SMOKE_PASSWORD")
    frontend_url = os.getenv("CATORA_SMOKE_FRONTEND_URL", "").strip().rstrip("/")

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    status, payload, _ = _request(opener, f"{api_url}/health/live")
    if status != 200 or _json(payload, label="Liveness").get("status") != "ok":
        raise RuntimeError("API liveness check failed")

    status, payload, _ = _request(opener, f"{api_url}/health/ready")
    readiness = _json(payload, label="Readiness")
    if status != 200 or readiness.get("status") != "ready":
        raise RuntimeError(f"API readiness check failed: {readiness}")

    _, payload, _ = _request(
        opener,
        f"{api_url}/api/v1/auth/login",
        method="POST",
        payload={"email": email, "password": password},
    )
    login = _json(payload, label="Login")
    workspace_id = _membership_workspace_id(login)

    _, payload, _ = _request(
        opener,
        f"{api_url}/api/v1/workspaces/{workspace_id}/demo",
    )
    overview = _json(payload, label="Demo overview")
    catalog = overview.get("catalog")
    recommendation = overview.get("recommendation")
    if not isinstance(catalog, dict) or int(catalog.get("product_count", 0)) < 1:
        raise RuntimeError("Demo overview contains no products")
    if not isinstance(recommendation, dict) or not recommendation.get("fields"):
        raise RuntimeError("Demo overview contains no reviewable recommendation fields")

    _, openapi_payload, _ = _request(opener, f"{api_url}/openapi.json")
    openapi = _json(openapi_payload, label="OpenAPI")
    paths = openapi.get("paths")
    decision_path = (
        "/api/v1/workspaces/{workspace_id}/demo/"
        "recommendations/{recommendation_id}/decision"
    )
    if not isinstance(paths, dict) or decision_path not in paths:
        raise RuntimeError("Recommendation decision route is missing from OpenAPI")

    report_path = overview.get("report_pptx_path")
    backlog_path = overview.get("operational_csv_path")
    if not isinstance(report_path, str) or not isinstance(backlog_path, str):
        raise RuntimeError("Demo download paths are missing")

    _, report, report_headers = _request(opener, f"{api_url}{report_path}")
    if not report.startswith(b"PK"):
        raise RuntimeError("Executive report is not a valid Office package")
    if "presentation" not in report_headers.get("Content-Type", ""):
        raise RuntimeError("Executive report has an unexpected content type")

    _, backlog, backlog_headers = _request(opener, f"{api_url}{backlog_path}")
    if b"field_key" not in backlog.splitlines()[0]:
        raise RuntimeError("Operational backlog is missing its expected header")
    if "csv" not in backlog_headers.get("Content-Type", ""):
        raise RuntimeError("Operational backlog has an unexpected content type")

    if frontend_url:
        status, _, _ = _request(opener, frontend_url)
        if status != 200:
            raise RuntimeError(f"Frontend returned status {status}")

    print(
        "Hosted demo smoke test passed: "
        f"workspace={workspace_id}, products={catalog['product_count']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Hosted demo smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
