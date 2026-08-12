from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BlockedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise BlockedError(f"Missing required staging configuration: {name}")
    return value


def _required_url(name: str) -> str:
    return _required(name).rstrip("/")


def _enabled(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().casefold()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise BlockedError(f"{name} must be true or false")


def _fetch(url: str, *, accept: str = "application/json") -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"Accept": accept}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to reach {url}: {type(exc).__name__}") from exc


def _json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return parsed


def _identity(
    *,
    component: str,
    payload: dict[str, Any],
    expected_sha: str,
    expected_ci_run_id: str,
    expected_digest: str,
) -> dict[str, str]:
    if payload.get("complete") is not True:
        raise BlockedError(f"{component} running release identity is incomplete")
    actual_component = payload.get("component")
    git_sha = payload.get("git_sha")
    ci_run_id = payload.get("ci_run_id")
    image_tag = payload.get("image_tag")
    image_digest = payload.get("image_digest")
    previous_image = payload.get("previous_image")
    values = (actual_component, git_sha, ci_run_id, image_tag, image_digest, previous_image)
    if not all(isinstance(value, str) and value for value in values):
        raise BlockedError(f"{component} running release identity contains missing fields")
    if actual_component != component:
        raise BlockedError(
            f"{component} identity endpoint reported component {actual_component!r}"
        )
    if git_sha.lower() != expected_sha.lower():
        raise BlockedError(
            f"{component} Git SHA mismatch: expected {expected_sha}, running {git_sha}"
        )
    if ci_run_id != expected_ci_run_id:
        raise BlockedError(
            f"{component} CI run mismatch: expected {expected_ci_run_id}, running {ci_run_id}"
        )
    if image_digest.lower() != expected_digest.lower():
        raise BlockedError(
            f"{component} image digest mismatch: expected {expected_digest}, running {image_digest}"
        )
    return {
        "component": component,
        "git_sha": git_sha,
        "ci_run_id": ci_run_id,
        "image_tag": image_tag,
        "image_digest": image_digest,
        "previous_image": previous_image,
    }


def _prove_identities(
    web_url: str,
    api_url: str,
    expected_sha: str,
    expected_ci_run_id: str,
    expected_digests: dict[str, str],
) -> tuple[dict[str, dict[str, str]], list[Check]]:
    identities: dict[str, dict[str, str]] = {}
    checks: list[Check] = []

    status, body, _ = _fetch(f"{web_url}/api/release")
    if status != 200:
        raise BlockedError(f"web release identity endpoint returned HTTP {status}")
    identities["web"] = _identity(
        component="web",
        payload=_json(body, label="Web release identity"),
        expected_sha=expected_sha,
        expected_ci_run_id=expected_ci_run_id,
        expected_digest=expected_digests["web"],
    )
    checks.append(Check("identity.web", "PASS", "running web artifact proven"))

    status, body, _ = _fetch(f"{api_url}/health/release")
    if status != 200:
        raise BlockedError(f"API release identity endpoint returned HTTP {status}")
    identities["api"] = _identity(
        component="api",
        payload=_json(body, label="API release identity"),
        expected_sha=expected_sha,
        expected_ci_run_id=expected_ci_run_id,
        expected_digest=expected_digests["api"],
    )
    checks.append(Check("identity.api", "PASS", "running API artifact proven"))

    status, body, _ = _fetch(f"{api_url}/health/worker")
    if status != 200:
        raise BlockedError(f"worker identity cannot be proven: /health/worker returned HTTP {status}")
    worker_ping = _json(body, label="Worker release identity")
    release = worker_ping.get("release")
    if worker_ping.get("status") != "ok" or not isinstance(release, dict):
        raise BlockedError("worker ping did not contain a valid release identity")
    identities["worker"] = _identity(
        component="worker",
        payload=release,
        expected_sha=expected_sha,
        expected_ci_run_id=expected_ci_run_id,
        expected_digest=expected_digests["worker"],
    )
    checks.append(Check("identity.worker", "PASS", "running Celery worker artifact proven"))
    return identities, checks


def _runtime_checks(web_url: str, api_url: str) -> list[Check]:
    checks: list[Check] = []
    status, body, headers = _fetch(f"{web_url}/login", accept="text/html")
    if status != 200 or "text/html" not in headers.get("Content-Type", "") or not body.strip():
        raise RuntimeError(f"frontend /login failed runtime health, HTTP {status}")
    checks.append(Check("runtime.web", "PASS", "frontend /login returned HTML"))

    status, body, _ = _fetch(f"{api_url}/health/live")
    live = _json(body, label="API liveness")
    if status != 200 or live.get("status") != "ok":
        raise RuntimeError(f"API liveness failed with HTTP {status}")
    checks.append(Check("runtime.api_live", "PASS", "API liveness is ok"))

    status, body, _ = _fetch(f"{api_url}/health/ready")
    ready = _json(body, label="API readiness")
    if status != 200 or ready.get("status") != "ready":
        raise RuntimeError(f"API readiness failed with HTTP {status}")
    dependencies = ready.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise RuntimeError("API readiness did not report dependency evidence")
    unhealthy = [
        str(item.get("name"))
        for item in dependencies
        if not isinstance(item, dict) or item.get("status") != "ok"
    ]
    if unhealthy:
        raise RuntimeError("API readiness has unhealthy dependencies: " + ", ".join(unhealthy))
    checks.append(
        Check(
            "runtime.dependencies",
            "PASS",
            "PostgreSQL, Redis and object-storage readiness checks passed",
        )
    )
    return checks


def _run_demo_smoke(
    *,
    web_url: str,
    api_url: str,
    report_dir: Path,
) -> Check:
    password = _required("CATORA_STAGING_DEMO_PASSWORD")
    env = dict(os.environ)
    env.update(
        {
            "CATORA_SMOKE_FRONTEND_URL": web_url,
            "CATORA_SMOKE_API_URL": api_url,
            "CATORA_SMOKE_EMAIL": "demo@catora.local",
            "CATORA_SMOKE_PASSWORD": password,
            "CATORA_SMOKE_REPORT_PATH": str(report_dir / "hosted-demo-smoke.json"),
            "CATORA_SMOKE_REQUIRE_SHOPIFY": (
                "true" if _enabled("CATORA_STAGING_REQUIRE_SHOPIFY") else "false"
            ),
        }
    )
    env.pop("CATORA_SMOKE_WORKSPACE_ID", None)
    result = subprocess.run(
        [sys.executable, "scripts/smoke_hosted_demo.py"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip())[-2_000:]
        raise RuntimeError(f"mandatory hosted demo smoke failed: {detail}")
    return Check(
        "product.hosted_demo",
        "PASS",
        "authenticated deterministic demo/API/report smoke passed",
    )


def _run_browser(report_dir: Path, run_id: str) -> tuple[Check, dict[str, Any]]:
    browser_report = report_dir / "staging-browser-evidence.json"
    env = dict(os.environ)
    env.update(
        {
            "CATORA_STAGING_BROWSER_REPORT": str(browser_report),
            "CATORA_STAGING_QA_RUN_ID": run_id,
        }
    )
    result = subprocess.run(
        [sys.executable, "scripts/staging_browser_certification.py"],
        env=env,
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )
    if not browser_report.exists():
        if result.returncode == 2:
            raise BlockedError("browser certification prerequisites are incomplete")
        raise RuntimeError("browser certification produced no evidence report")
    payload = json.loads(browser_report.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("browser certification evidence is invalid")
    browser_decision = payload.get("decision")
    if browser_decision == "BLOCKED" or result.returncode == 2:
        detail = payload.get("detail")
        raise BlockedError(
            str(detail) if isinstance(detail, str) else "browser certification is blocked"
        )
    if browser_decision != "PASS" or result.returncode != 0:
        detail = payload.get("detail")
        raise RuntimeError(
            str(detail) if isinstance(detail, str) else "browser certification failed"
        )
    return (
        Check(
            "browser.playwright",
            "PASS",
            "desktop/mobile authentication, RBAC and core journeys passed",
        ),
        payload,
    )


def _run_visual(report_dir: Path) -> tuple[Check, dict[str, Any]]:
    visual_report = report_dir / "staging-visual-evidence.json"
    env = dict(os.environ)
    env["CATORA_STAGING_VISUAL_REPORT"] = str(visual_report)
    result = subprocess.run(
        [sys.executable, "scripts/staging_visual_certification.py"],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if not visual_report.exists():
        if result.returncode == 2:
            raise BlockedError("visual certification prerequisites are incomplete")
        raise RuntimeError("visual certification produced no evidence report")
    payload = json.loads(visual_report.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("visual certification evidence is invalid")
    visual_decision = payload.get("decision")
    if visual_decision == "BLOCKED" or result.returncode == 2:
        detail = payload.get("detail")
        raise BlockedError(
            str(detail) if isinstance(detail, str) else "VISUAL REVIEW REQUIRED"
        )
    if visual_decision != "PASS" or result.returncode != 0:
        detail = payload.get("detail")
        raise RuntimeError(
            str(detail) if isinstance(detail, str) else "visual certification failed"
        )
    return (
        Check(
            "visual.playwright",
            "PASS",
            "approved desktop/mobile screenshot baselines matched",
        ),
        payload,
    )


def _write_html(path: Path, report: dict[str, Any]) -> None:
    rows = []
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(check.get('name', '')))}</td>"
            f"<td>{html.escape(str(check.get('status', '')))}</td>"
            f"<td>{html.escape(str(check.get('detail', '')))}</td>"
            "</tr>"
        )
    identities = report.get("identities")
    identity_html = html.escape(json.dumps(identities, indent=2, sort_keys=True))
    document = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Catora staging certification</title></head>
<body>
<h1>Catora staging certification</h1>
<p><strong>Decision:</strong> {html.escape(str(report.get('decision', '')))}</p>
<p><strong>QA run:</strong> {html.escape(str(report.get('qa_run_id', '')))}</p>
<table border="1" cellspacing="0" cellpadding="6">
<thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<h2>Release identity</h2><pre>{identity_html}</pre>
</body></html>
"""
    path.write_text(document, encoding="utf-8")


def main() -> int:
    started = int(time.time())
    run_id = os.getenv("CATORA_STAGING_QA_RUN_ID", "").strip() or str(started)
    report_dir = Path(os.getenv("CATORA_STAGING_REPORT_DIR", "staging-certification-artifacts"))
    report_dir.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    identities: dict[str, dict[str, str]] = {}
    browser_evidence: dict[str, Any] | None = None
    visual_evidence: dict[str, Any] | None = None
    decision = "FAILED"
    detail = "staging certification did not complete"

    try:
        web_url = _required_url("CATORA_STAGING_WEB_URL")
        api_url = _required_url("CATORA_STAGING_API_URL")
        expected_sha = _required("CATORA_STAGING_EXPECTED_GIT_SHA").lower()
        expected_ci_run_id = _required("CATORA_STAGING_EXPECTED_CI_RUN_ID")
        _required("CATORA_STAGING_QA_WORKSPACE_ID")
        expected_digests = {
            "web": _required("CATORA_STAGING_WEB_IMAGE_DIGEST").lower(),
            "api": _required("CATORA_STAGING_API_IMAGE_DIGEST").lower(),
            "worker": _required("CATORA_STAGING_WORKER_IMAGE_DIGEST").lower(),
        }

        identities, identity_checks = _prove_identities(
            web_url,
            api_url,
            expected_sha,
            expected_ci_run_id,
            expected_digests,
        )
        checks.extend(identity_checks)
        checks.extend(_runtime_checks(web_url, api_url))
        checks.append(
            _run_demo_smoke(
                web_url=web_url,
                api_url=api_url,
                report_dir=report_dir,
            )
        )
        browser_check, browser_evidence = _run_browser(report_dir, run_id)
        checks.append(browser_check)
        visual_check, visual_evidence = _run_visual(report_dir)
        checks.append(visual_check)
        decision = "READY FOR UAT"
        detail = "all mandatory supported staging certification gates passed"
        exit_code = 0
    except BlockedError as exc:
        decision = "BLOCKED"
        detail = str(exc)
        exit_code = 2
    except Exception as exc:
        decision = "FAILED"
        detail = f"{type(exc).__name__}: {exc}"
        exit_code = 1

    report: dict[str, Any] = {
        "schema": "catora-staging-certification/v1",
        "qa_run_id": run_id,
        "timestamp_unix": started,
        "decision": decision,
        "detail": detail,
        "identities": identities,
        "checks": [asdict(check) for check in checks],
    }
    if browser_evidence is not None:
        browser_checks = browser_evidence.get("checks")
        if isinstance(browser_checks, list):
            report["browser_check_count"] = len(browser_checks)
    if visual_evidence is not None:
        visual_checks = visual_evidence.get("checks")
        if isinstance(visual_checks, list):
            report["visual_check_count"] = len(visual_checks)

    json_path = report_dir / "staging-certification.json"
    html_path = report_dir / "staging-certification.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_html(html_path, report)

    print(decision)
    print(detail)
    print(f"Sanitized JSON evidence: {json_path}")
    print(f"Sanitized HTML evidence: {html_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
