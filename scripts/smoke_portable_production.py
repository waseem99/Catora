from __future__ import annotations

import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _url(name: str) -> str:
    return _required(name).rstrip("/")


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    accept: str = "application/json",
) -> tuple[int, bytes, dict[str, str]]:
    body = None
    headers = {"Accept": accept, "User-Agent": "catora-portable-production-smoke/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            return (
                response.status,
                response.read(2_000_000),
                {key.casefold(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read(2_000).decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed network/TLS validation: {exc.reason}") from exc


def _json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return parsed


def _expected(name: str, pattern: re.Pattern[str]) -> str | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    if not pattern.fullmatch(value):
        raise RuntimeError(f"{name} has an invalid format")
    return value


def _assert_release(
    *,
    component: str,
    payload: dict[str, Any],
    expected_sha: str | None,
    expected_digest: str | None,
) -> dict[str, str]:
    if payload.get("complete") is not True:
        raise RuntimeError(f"{component} release identity is incomplete")
    actual_component = str(payload.get("component", ""))
    git_sha = str(payload.get("git_sha", "")).lower()
    digest = str(payload.get("image_digest", "")).lower()
    ci_run_id = str(payload.get("ci_run_id", ""))
    if actual_component != component:
        raise RuntimeError(f"{component} endpoint reported component {actual_component!r}")
    if not SHA_RE.fullmatch(git_sha) or not DIGEST_RE.fullmatch(digest) or not ci_run_id:
        raise RuntimeError(f"{component} release identity is malformed")
    if expected_sha and git_sha != expected_sha:
        raise RuntimeError(
            f"{component} Git SHA mismatch: expected {expected_sha}, running {git_sha}"
        )
    if expected_digest and digest != expected_digest:
        raise RuntimeError(
            f"{component} digest mismatch: expected {expected_digest}, running {digest}"
        )
    return {"git_sha": git_sha, "image_digest": digest, "ci_run_id": ci_run_id}


def _workspace_id(login: dict[str, Any]) -> tuple[str, str]:
    configured = os.getenv("CATORA_PORTABLE_SMOKE_WORKSPACE_ID", "").strip()
    user = login.get("user")
    if not isinstance(user, dict):
        raise RuntimeError("Login response is missing user data")
    memberships = user.get("memberships")
    if not isinstance(memberships, list) or not memberships:
        raise RuntimeError("Login succeeded but no workspace membership was returned")

    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        workspace_id = membership.get("workspace_id")
        role = membership.get("role")
        if not isinstance(workspace_id, str) or not isinstance(role, str):
            continue
        if not configured or configured == workspace_id:
            return workspace_id, role
    raise RuntimeError("Configured production smoke workspace is not available to this account")


def _write_report(report: dict[str, object]) -> None:
    path_value = os.getenv("CATORA_PORTABLE_SMOKE_REPORT_PATH", "").strip()
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    frontend_url = _url("CATORA_PORTABLE_SMOKE_FRONTEND_URL")
    api_url = _url("CATORA_PORTABLE_SMOKE_API_URL")
    email = _required("CATORA_PORTABLE_SMOKE_EMAIL")
    password = _required("CATORA_PORTABLE_SMOKE_PASSWORD")
    expected_sha = _expected("CATORA_PORTABLE_SMOKE_EXPECTED_GIT_SHA", SHA_RE)
    expected_digests = {
        "web": _expected("CATORA_PORTABLE_SMOKE_EXPECTED_WEB_DIGEST", DIGEST_RE),
        "api": _expected("CATORA_PORTABLE_SMOKE_EXPECTED_API_DIGEST", DIGEST_RE),
        "worker": _expected("CATORA_PORTABLE_SMOKE_EXPECTED_WORKER_DIGEST", DIGEST_RE),
    }
    min_products_text = os.getenv("CATORA_PORTABLE_SMOKE_MIN_PRODUCTS", "0").strip() or "0"
    if not min_products_text.isdigit():
        raise RuntimeError("CATORA_PORTABLE_SMOKE_MIN_PRODUCTS must be a non-negative integer")
    min_products = int(min_products_text)

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    report: dict[str, object] = {
        "frontend_url": frontend_url,
        "api_url": api_url,
        "expected_git_sha": expected_sha,
        "checks": [],
    }

    status, body, headers = _request(opener, f"{frontend_url}/login", accept="text/html")
    if status != 200 or "text/html" not in headers.get("content-type", "") or b"Catora" not in body:
        raise RuntimeError("Frontend /login did not return the Catora application")
    report["checks"].append({"name": "frontend.login", "status": "PASS"})

    status, body, _ = _request(opener, f"{api_url}/health/live")
    live = _json(body, label="API liveness")
    if status != 200 or live.get("status") != "ok":
        raise RuntimeError(f"API liveness failed: {live}")
    report["checks"].append({"name": "api.live", "status": "PASS"})

    status, body, _ = _request(opener, f"{api_url}/health/ready")
    ready = _json(body, label="API readiness")
    if status != 200 or ready.get("status") != "ready":
        raise RuntimeError(f"API readiness failed: {ready}")
    dependencies = ready.get("dependencies")
    if not isinstance(dependencies, list) or any(
        not isinstance(item, dict) or item.get("status") != "ok" for item in dependencies
    ):
        raise RuntimeError(f"API readiness dependencies are unhealthy: {dependencies}")
    report["checks"].append({"name": "api.dependencies", "status": "PASS"})

    _, body, _ = _request(opener, f"{frontend_url}/api/release")
    report["web_release"] = _assert_release(
        component="web",
        payload=_json(body, label="Web release"),
        expected_sha=expected_sha,
        expected_digest=expected_digests["web"],
    )
    _, body, _ = _request(opener, f"{api_url}/health/release")
    report["api_release"] = _assert_release(
        component="api",
        payload=_json(body, label="API release"),
        expected_sha=expected_sha,
        expected_digest=expected_digests["api"],
    )
    _, body, _ = _request(opener, f"{api_url}/health/worker")
    worker = _json(body, label="Worker release")
    worker_release = worker.get("release")
    if worker.get("status") != "ok" or not isinstance(worker_release, dict):
        raise RuntimeError("Worker health endpoint did not prove a running worker")
    report["worker_release"] = _assert_release(
        component="worker",
        payload=worker_release,
        expected_sha=expected_sha,
        expected_digest=expected_digests["worker"],
    )
    report["checks"].append({"name": "release.identity", "status": "PASS"})

    _, body, _ = _request(
        opener,
        f"{api_url}/api/v1/auth/login",
        method="POST",
        payload={"email": email, "password": password},
    )
    login = _json(body, label="Login")
    workspace_id, role = _workspace_id(login)
    report["workspace_id"] = workspace_id
    report["workspace_role"] = role
    report["checks"].append({"name": "authentication.workspace", "status": "PASS"})

    _, body, _ = _request(
        opener,
        f"{api_url}/api/v1/workspaces/{workspace_id}/products?limit=1&offset=0",
    )
    products = _json(body, label="Catalog read")
    total = products.get("total")
    items = products.get("items")
    if not isinstance(total, int) or isinstance(total, bool) or total < min_products:
        raise RuntimeError(
            f"Restored catalog has {total!r} products; expected at least {min_products}"
        )
    if not isinstance(items, list):
        raise RuntimeError("Catalog read did not return an item list")
    report["catalog_total"] = total
    report["checks"].append({"name": "catalog.read", "status": "PASS"})

    report["decision"] = "PASS"
    _write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - bounded operator acceptance diagnostic
        print(f"Portable production smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
