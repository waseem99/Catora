from __future__ import annotations

import csv
import http.cookiejar
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

EXPECTED_PRODUCTS = 1_000
EXPECTED_VARIANTS = 2_000
EXPECTED_SHOP = "northstar-living-demo.myshopify.com"
EXPECTED_SCOPES = {"read_products"}
EXPECTED_CSV_COLUMNS = {
    "product_id",
    "product_title",
    "record_type",
    "severity_or_state",
    "field_key",
    "current_value",
    "proposed_or_remediation",
    "evidence",
    "verification_required",
}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _required_url(name: str) -> str:
    return _required(name).rstrip("/")


def _enabled(name: str) -> bool:
    value = os.getenv(name, "").strip().casefold()
    if value in {"", "0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    raise RuntimeError(f"{name} must be true or false")


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    accept: str = "application/json",
) -> tuple[int, bytes, dict[str, str]]:
    body = None
    headers = {"Accept": accept}
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


def _nonnegative_int(mapping: dict[str, Any], key: str, *, label: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{label} is missing a valid {key}")
    return value


def _validate_preflight(preflight: dict[str, Any]) -> dict[str, object]:
    if preflight.get("ready") is not True:
        raise RuntimeError(f"Presenter preflight is not ready: {preflight}")
    components = preflight.get("components")
    if not isinstance(components, list) or not components:
        raise RuntimeError("Presenter preflight contains no component results")
    unhealthy: list[str] = []
    component_keys: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            raise RuntimeError("Presenter preflight contains an invalid component result")
        key = component.get("key")
        state = component.get("state")
        if not isinstance(key, str) or not key:
            raise RuntimeError("Presenter preflight component key is missing")
        component_keys.append(key)
        if state != "ok":
            unhealthy.append(f"{key}:{state}")
    if unhealthy:
        raise RuntimeError("Presenter preflight has unhealthy components: " + ", ".join(unhealthy))

    snapshot = preflight.get("last_verified_snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError("Presenter preflight is missing the last verified snapshot")
    products = _nonnegative_int(snapshot, "product_count", label="Verified snapshot")
    variants = _nonnegative_int(snapshot, "variant_count", label="Verified snapshot")
    if products != EXPECTED_PRODUCTS or variants != EXPECTED_VARIANTS:
        raise RuntimeError(
            "Verified snapshot scale mismatch: "
            f"expected {EXPECTED_PRODUCTS}/{EXPECTED_VARIANTS}, got {products}/{variants}"
        )
    if not snapshot.get("audit_run_id") or not snapshot.get("verified_at"):
        raise RuntimeError("Verified snapshot is missing audit or verification metadata")
    return {
        "ready": True,
        "components": component_keys,
        "product_count": products,
        "variant_count": variants,
        "verified_at": snapshot["verified_at"],
    }


def _validate_overview(overview: dict[str, Any]) -> dict[str, object]:
    catalog = overview.get("catalog")
    recommendation = overview.get("recommendation")
    intent = overview.get("intent")
    hero_product = overview.get("hero_product")
    if not isinstance(catalog, dict):
        raise RuntimeError("Demo overview is missing catalog totals")
    products = _nonnegative_int(catalog, "product_count", label="Demo catalog")
    variants = _nonnegative_int(catalog, "variant_count", label="Demo catalog")
    if products != EXPECTED_PRODUCTS or variants != EXPECTED_VARIANTS:
        raise RuntimeError(
            "Demo catalog scale mismatch: "
            f"expected {EXPECTED_PRODUCTS}/{EXPECTED_VARIANTS}, got {products}/{variants}"
        )
    if not isinstance(recommendation, dict) or not recommendation.get("fields"):
        raise RuntimeError("Demo overview contains no reviewable recommendation fields")
    if not isinstance(intent, dict) or not intent.get("explanation"):
        raise RuntimeError("Demo overview contains no buyer-intent impact")
    if not isinstance(hero_product, dict) or not hero_product.get("source_evidence"):
        raise RuntimeError("Demo overview contains no hero-product source evidence")
    return {
        "product_count": products,
        "variant_count": variants,
        "recommendation_id": recommendation.get("id"),
        "hero_product": hero_product.get("title"),
    }


def _validate_shopify_installation(installation: dict[str, Any]) -> dict[str, object]:
    if installation.get("shop_domain") != EXPECTED_SHOP:
        raise RuntimeError("Catora is not connected to the canonical Northstar Shopify store")
    if installation.get("status") != "active" or installation.get("health") != "healthy":
        raise RuntimeError(
            "Shopify installation is not active and healthy: "
            f"status={installation.get('status')}, health={installation.get('health')}"
        )
    scopes = installation.get("granted_scopes")
    granted = {item for item in scopes if isinstance(item, str)} if isinstance(scopes, list) else set()
    if granted != EXPECTED_SCOPES:
        raise RuntimeError(f"Shopify scopes do not equal read_products: {scopes}")
    if installation.get("token_mode") != "expiring_offline":
        raise RuntimeError("Shopify installation is not using expiring offline tokens")
    if installation.get("sync_status") != "completed":
        raise RuntimeError(
            f"Shopify initial synchronization is not completed: {installation.get('sync_status')}"
        )
    products = _nonnegative_int(installation, "product_count", label="Shopify installation")
    variants = _nonnegative_int(installation, "variant_count", label="Shopify installation")
    if products != EXPECTED_PRODUCTS or variants != EXPECTED_VARIANTS:
        raise RuntimeError(
            "Shopify synchronization scale mismatch: "
            f"expected {EXPECTED_PRODUCTS}/{EXPECTED_VARIANTS}, got {products}/{variants}"
        )
    if not installation.get("last_successful_sync_at") or not installation.get(
        "last_audit_run_id"
    ):
        raise RuntimeError("Shopify installation is missing successful sync or audit metadata")
    return {
        "shop_domain": EXPECTED_SHOP,
        "health": "healthy",
        "sync_status": "completed",
        "product_count": products,
        "variant_count": variants,
        "last_successful_sync_at": installation["last_successful_sync_at"],
    }


def _validate_pptx(payload: bytes, content_type: str) -> dict[str, object]:
    if "presentation" not in content_type:
        raise RuntimeError("Executive report has an unexpected content type")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Executive report is not a valid Office package") from exc
    required = {"[Content_Types].xml", "ppt/presentation.xml", "ppt/slides/slide1.xml"}
    missing = sorted(required - names)
    if missing:
        raise RuntimeError("Executive report is missing required PPTX parts: " + ", ".join(missing))
    if any(name.endswith("vbaProject.bin") for name in names):
        raise RuntimeError("Executive report unexpectedly contains a VBA project")
    slide_count = sum(
        1 for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    )
    if slide_count < 1:
        raise RuntimeError("Executive report contains no editable slides")
    return {"size_bytes": len(payload), "slide_count": slide_count}


def _validate_csv(payload: bytes, content_type: str) -> dict[str, object]:
    if "csv" not in content_type:
        raise RuntimeError("Operational backlog has an unexpected content type")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Operational backlog is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    missing = sorted(EXPECTED_CSV_COLUMNS - columns)
    if missing:
        raise RuntimeError("Operational backlog is missing columns: " + ", ".join(missing))
    rows = list(reader)
    if not rows:
        raise RuntimeError("Operational backlog contains no actionable rows")
    record_types = {row.get("record_type") for row in rows}
    if not {"finding", "recommendation"}.issubset(record_types):
        raise RuntimeError("Operational backlog must contain finding and recommendation rows")
    return {"row_count": len(rows), "columns": sorted(columns)}


def _write_report(report: dict[str, object]) -> None:
    path_value = os.getenv("CATORA_SMOKE_REPORT_PATH", "").strip()
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    api_url = _required_url("CATORA_SMOKE_API_URL")
    email = _required("CATORA_SMOKE_EMAIL")
    password = _required("CATORA_SMOKE_PASSWORD")
    frontend_url = os.getenv("CATORA_SMOKE_FRONTEND_URL", "").strip().rstrip("/")
    require_shopify = _enabled("CATORA_SMOKE_REQUIRE_SHOPIFY")

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    report: dict[str, object] = {
        "frontend_url": frontend_url or None,
        "api_url": api_url,
        "shopify_required": require_shopify,
    }

    status, payload, _ = _request(opener, f"{api_url}/health/live")
    if status != 200 or _json(payload, label="Liveness").get("status") != "ok":
        raise RuntimeError("API liveness check failed")
    report["api_liveness"] = "ok"

    status, payload, _ = _request(opener, f"{api_url}/health/ready")
    readiness = _json(payload, label="Readiness")
    if status != 200 or readiness.get("status") != "ready":
        raise RuntimeError(f"API readiness check failed: {readiness}")
    report["api_readiness"] = readiness

    _, payload, _ = _request(
        opener,
        f"{api_url}/api/v1/auth/login",
        method="POST",
        payload={"email": email, "password": password},
    )
    login = _json(payload, label="Login")
    workspace_id = _membership_workspace_id(login)
    report["workspace_id"] = workspace_id

    _, payload, _ = _request(
        opener,
        f"{api_url}/api/v1/workspaces/{workspace_id}/demo/preflight",
    )
    report["preflight"] = _validate_preflight(_json(payload, label="Presenter preflight"))

    _, payload, _ = _request(
        opener,
        f"{api_url}/api/v1/workspaces/{workspace_id}/demo",
    )
    overview = _json(payload, label="Demo overview")
    report["demo"] = _validate_overview(overview)

    _, openapi_payload, _ = _request(opener, f"{api_url}/openapi.json")
    openapi = _json(openapi_payload, label="OpenAPI")
    paths = openapi.get("paths")
    decision_path = (
        "/api/v1/workspaces/{workspace_id}/demo/"
        "recommendations/{recommendation_id}/decision"
    )
    if not isinstance(paths, dict) or decision_path not in paths:
        raise RuntimeError("Recommendation decision route is missing from OpenAPI")
    report["recommendation_decision_route"] = "registered"

    report_path = overview.get("report_pptx_path")
    backlog_path = overview.get("operational_csv_path")
    if not isinstance(report_path, str) or not isinstance(backlog_path, str):
        raise RuntimeError("Demo download paths are missing")

    _, pptx_payload, pptx_headers = _request(
        opener,
        f"{api_url}{report_path}",
        accept="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    report["pptx"] = _validate_pptx(
        pptx_payload,
        pptx_headers.get("Content-Type", ""),
    )

    _, csv_payload, csv_headers = _request(
        opener,
        f"{api_url}{backlog_path}",
        accept="text/csv",
    )
    report["operational_csv"] = _validate_csv(
        csv_payload,
        csv_headers.get("Content-Type", ""),
    )

    if require_shopify:
        _, payload, _ = _request(
            opener,
            f"{api_url}/api/v1/workspaces/{workspace_id}/shopify/installation",
        )
        report["shopify"] = _validate_shopify_installation(
            _json(payload, label="Shopify installation")
        )
    else:
        report["shopify"] = {"status": "skipped"}

    if frontend_url:
        status, frontend_payload, frontend_headers = _request(
            opener,
            f"{frontend_url}/login",
            accept="text/html",
        )
        if status != 200:
            raise RuntimeError(f"Frontend login returned status {status}")
        if "text/html" not in frontend_headers.get("Content-Type", ""):
            raise RuntimeError("Frontend login has an unexpected content type")
        if not frontend_payload.strip():
            raise RuntimeError("Frontend login returned an empty response")
        report["frontend"] = {"login": "ok"}

    report["status"] = "passed"
    _write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Hosted demo smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
