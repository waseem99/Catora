from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CERTIFICATION = runpy.run_path(str(ROOT / "scripts" / "staging_certify.py"))
BlockedError = CERTIFICATION["BlockedError"]
identity = CERTIFICATION["_identity"]


def _payload() -> dict[str, object]:
    return {
        "component": "api",
        "git_sha": "a" * 40,
        "ci_run_id": "42",
        "image_tag": "ghcr.io/waseem99/catora-api:sha-aaaa",
        "image_digest": "sha256:" + "b" * 64,
        "previous_image": "sha256:" + "c" * 64,
        "complete": True,
    }


def test_identity_gate_accepts_exact_running_artifact() -> None:
    result = identity(
        component="api",
        payload=_payload(),
        expected_sha="a" * 40,
        expected_ci_run_id="42",
        expected_digest="sha256:" + "b" * 64,
    )

    assert result["git_sha"] == "a" * 40
    assert result["image_digest"] == "sha256:" + "b" * 64


def test_identity_gate_blocks_wrong_running_digest() -> None:
    with pytest.raises(BlockedError, match="image digest mismatch"):
        identity(
            component="api",
            payload=_payload(),
            expected_sha="a" * 40,
            expected_ci_run_id="42",
            expected_digest="sha256:" + "d" * 64,
        )


def test_identity_gate_blocks_incomplete_runtime_evidence() -> None:
    payload = _payload()
    payload["complete"] = False

    with pytest.raises(BlockedError, match="identity is incomplete"):
        identity(
            component="api",
            payload=payload,
            expected_sha="a" * 40,
            expected_ci_run_id="42",
            expected_digest="sha256:" + "b" * 64,
        )


def test_browser_certification_keeps_required_real_product_coverage() -> None:
    browser = (ROOT / "scripts" / "staging_browser_certification.py").read_text(
        encoding="utf-8"
    )
    required_markers = {
        '"desktop-chromium"': "desktop Chromium profile",
        '"mobile-chromium"': "mobile Chromium profile",
        "authentication.protected_route": "unauthenticated route guard",
        "authentication.invalid_login": "invalid login",
        "authentication.forgot_password_enumeration": "forgot-password enumeration defense",
        "authentication.reset_invalid_token": "invalid password reset token",
        "authentication.invitation_invalid_token": "invalid invitation token",
        "member_manage_api": "server-side member-management denial",
        "identity_manage_api": "server-side identity-management denial",
        "cross_workspace_api": "cross-workspace API isolation",
        "cross_workspace_browser": "cross-workspace browser isolation",
        "no_membership.api": "no-membership API isolation",
        "catalog.search": "catalog search",
        "catalog.warning_filter": "catalog warning filter",
        "catalog.clean_filter": "catalog clean filter",
        "catalog.pagination": "catalog pagination",
        "catalog.product_detail": "product detail and provenance",
        "demo.presenter_preflight": "presenter preflight",
        "onboarding.authorization_gate": "catalog onboarding authorization gate",
        "processing.persisted_status": "persisted processing status",
        "service_visibility.authorization_gate": "Service Visibility authorization gate",
        "measurement.managed_credential_reference": "managed Google credential reference",
        "mobile.layout.": "mobile overflow checks",
        ".pageerror": "uncaught browser page errors",
        ".requestfailed": "failed browser requests",
        ".http5xx": "browser-observed HTTP 5xx responses",
    }
    missing = [
        description
        for marker, description in required_markers.items()
        if marker not in browser
    ]
    assert not missing, f"Mandatory staging browser coverage removed: {', '.join(missing)}"

    for role in ("OWNER", "ADMIN", "ANALYST", "REVIEWER", "VIEWER"):
        assert f"CATORA_STAGING_{role}_EMAIL" in browser
        assert f"CATORA_STAGING_{role}_PASSWORD" in browser
    assert "CATORA_STAGING_NO_MEMBERSHIP_EMAIL" in browser
    assert "CATORA_STAGING_NO_MEMBERSHIP_PASSWORD" in browser


def test_browser_auth_errors_target_catora_form_errors_not_framework_announcers() -> None:
    browser = (ROOT / "scripts" / "staging_browser_certification.py").read_text(
        encoding="utf-8"
    )

    assert 'page.locator(\'p.form-error[role="alert"]\')' in browser
    assert '_form_error(page, label="invalid login")' in browser
    assert '_form_error(page, label="invalid password-reset token")' in browser
    assert '_form_error(page, label="invalid invitation token")' in browser
    assert 'page.get_by_role("alert")' not in browser


def test_staging_demo_smoke_uses_seeded_demo_identity_and_masks_ephemeral_secrets() -> None:
    certify = (ROOT / "scripts" / "staging_certify.py").read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "staging-deploy-compose.yml"
    ).read_text(encoding="utf-8")

    assert '"CATORA_SMOKE_EMAIL": "demo@catora.local"' in certify
    assert '_required("CATORA_STAGING_DEMO_PASSWORD")' in certify
    assert 'env.pop("CATORA_SMOKE_WORKSPACE_ID", None)' in certify
    assert '"CATORA_SMOKE_WORKSPACE_ID": workspace_id' not in certify
    assert 'print(f"::add-mask::{value}")' in workflow


def test_hosted_demo_smoke_normalizes_response_header_names() -> None:
    smoke = (ROOT / "scripts" / "smoke_hosted_demo.py").read_text(encoding="utf-8")

    assert "key.casefold(): value" in smoke
    assert 'pptx_headers.get("content-type", "")' in smoke
    assert 'csv_headers.get("content-type", "")' in smoke
    assert 'frontend_headers.get("content-type", "")' in smoke
    assert '.get("Content-Type", "")' not in smoke
