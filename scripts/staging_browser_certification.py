from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

ROLE_ENV = {
    "owner": ("CATORA_STAGING_OWNER_EMAIL", "CATORA_STAGING_OWNER_PASSWORD"),
    "admin": ("CATORA_STAGING_ADMIN_EMAIL", "CATORA_STAGING_ADMIN_PASSWORD"),
    "analyst": ("CATORA_STAGING_ANALYST_EMAIL", "CATORA_STAGING_ANALYST_PASSWORD"),
    "reviewer": ("CATORA_STAGING_REVIEWER_EMAIL", "CATORA_STAGING_REVIEWER_PASSWORD"),
    "viewer": ("CATORA_STAGING_VIEWER_EMAIL", "CATORA_STAGING_VIEWER_PASSWORD"),
}
NO_MEMBERSHIP_ENV = (
    "CATORA_STAGING_NO_MEMBERSHIP_EMAIL",
    "CATORA_STAGING_NO_MEMBERSHIP_PASSWORD",
)


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


def _credential(email_name: str, password_name: str) -> tuple[str, str]:
    email = _required(email_name)
    password = _required(password_name)
    return email, password


def _base_url(name: str) -> str:
    return _required(name).rstrip("/")


def _direct_api_headers(
    context: BrowserContext,
    web_url: str,
    *,
    include_csrf: bool = False,
) -> dict[str, str]:
    cookies = {
        str(cookie.get("name")): str(cookie.get("value"))
        for cookie in context.cookies(web_url)
        if cookie.get("name") in {"catora_session", "catora_csrf"}
    }
    session = cookies.get("catora_session")
    if not session:
        raise RuntimeError("Authenticated browser context is missing the session cookie")
    headers = {
        "Cookie": "; ".join(
            f"{name}={value}" for name, value in sorted(cookies.items())
        )
    }
    if include_csrf:
        csrf = cookies.get("catora_csrf")
        if not csrf:
            raise RuntimeError("Authenticated browser context is missing the CSRF cookie")
        headers["X-CSRF-Token"] = csrf
    return headers


def _login(page: Page, web_url: str, email: str, password: str) -> None:
    page.goto(f"{web_url}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_role(
        "heading", name="Sign in to your commerce intelligence workspace."
    ).wait_for(state="visible", timeout=15_000)
    page.get_by_label("Work email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/workspaces", timeout=20_000)
    page.get_by_role("button", name="Sign out").wait_for(state="visible", timeout=15_000)


def _membership_role(payload: dict[str, Any], workspace_id: str) -> str | None:
    memberships = payload.get("memberships")
    if not isinstance(memberships, list):
        raise RuntimeError("auth/me did not return memberships")
    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        if membership.get("workspace_id") == workspace_id:
            role = membership.get("role")
            return role if isinstance(role, str) else None
    return None


def _run_role(
    *,
    context: BrowserContext,
    page: Page,
    web_url: str,
    api_url: str,
    workspace_id: str,
    denied_workspace_id: str,
    role: str,
    email: str,
    password: str,
    run_id: str,
) -> list[Check]:
    checks: list[Check] = []
    _login(page, web_url, email, password)
    checks.append(Check(f"{role}.login", "PASS", "UI login reached /workspaces"))

    direct_headers = _direct_api_headers(context, web_url)
    me = context.request.get(
        f"{api_url}/api/v1/auth/me",
        headers=direct_headers,
        timeout=15_000,
    )
    if me.status != 200:
        raise RuntimeError(f"{role}: auth/me returned HTTP {me.status}")
    payload = me.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{role}: auth/me returned an invalid payload")
    actual_role = _membership_role(payload, workspace_id)
    if actual_role != role:
        raise RuntimeError(
            f"{role}: expected staging membership role {role}, got {actual_role or 'none'}"
        )
    checks.append(Check(f"{role}.membership", "PASS", f"workspace role is {role}"))

    page.goto(f"{web_url}/workspace/{workspace_id}/members", wait_until="domcontentloaded")
    page.get_by_role("heading", name="Workspace members").wait_for(
        state="visible", timeout=15_000
    )
    invite_button = page.get_by_role("button", name="Invite member")
    if role in {"owner", "admin"}:
        invite_button.wait_for(state="visible", timeout=10_000)
        checks.append(
            Check(
                f"{role}.member_manage_ui",
                "PASS",
                "member-management controls are available",
            )
        )
    else:
        if invite_button.count() != 0:
            raise RuntimeError(f"{role}: member-management controls leaked into the UI")
        checks.append(
            Check(
                f"{role}.member_manage_ui",
                "PASS",
                "member-management controls are absent",
            )
        )
        denied = context.request.post(
            f"{api_url}/api/v1/workspaces/{workspace_id}/invitations",
            data={
                "email": f"qa-denied-{run_id}@example.invalid",
                "role": "viewer",
            },
            headers=_direct_api_headers(context, web_url, include_csrf=True),
            timeout=15_000,
        )
        if denied.status != 403:
            raise RuntimeError(
                f"{role}: prohibited invitation mutation returned HTTP {denied.status}, expected 403"
            )
        checks.append(
            Check(
                f"{role}.member_manage_api",
                "PASS",
                "prohibited invitation mutation returned 403",
            )
        )

    cross_workspace = context.request.get(
        f"{api_url}/api/v1/workspaces/{denied_workspace_id}/members",
        headers=direct_headers,
        timeout=15_000,
    )
    if cross_workspace.status != 403:
        raise RuntimeError(
            f"{role}: cross-workspace member request returned HTTP "
            f"{cross_workspace.status}, expected 403"
        )
    checks.append(
        Check(
            f"{role}.cross_workspace",
            "PASS",
            "cross-workspace member request returned 403",
        )
    )

    page.goto(f"{web_url}/workspaces", wait_until="domcontentloaded")
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url("**/login", timeout=15_000)
    after_logout = context.request.get(
        f"{api_url}/api/v1/auth/me",
        headers=direct_headers,
        timeout=15_000,
    )
    if after_logout.status != 401:
        raise RuntimeError(
            f"{role}: revoked session returned HTTP {after_logout.status} after logout, expected 401"
        )
    checks.append(
        Check(f"{role}.logout", "PASS", "pre-logout session token was revoked server-side")
    )
    return checks


def _run_no_membership(
    *,
    context: BrowserContext,
    page: Page,
    web_url: str,
    api_url: str,
    workspace_id: str,
    email: str,
    password: str,
) -> list[Check]:
    _login(page, web_url, email, password)
    direct_headers = _direct_api_headers(context, web_url)
    me = context.request.get(
        f"{api_url}/api/v1/auth/me",
        headers=direct_headers,
        timeout=15_000,
    )
    if me.status != 200:
        raise RuntimeError(f"no-membership identity: auth/me returned HTTP {me.status}")
    payload = me.json()
    if not isinstance(payload, dict):
        raise RuntimeError("no-membership identity: invalid auth/me payload")
    if _membership_role(payload, workspace_id) is not None:
        raise RuntimeError("no-membership identity unexpectedly belongs to the QA workspace")

    direct_api = context.request.get(
        f"{api_url}/api/v1/workspaces/{workspace_id}/members",
        headers=direct_headers,
        timeout=15_000,
    )
    if direct_api.status != 403:
        raise RuntimeError(
            "no-membership identity: protected workspace API returned "
            f"HTTP {direct_api.status}, expected 403"
        )

    page.goto(f"{web_url}/workspace/{workspace_id}/members", wait_until="domcontentloaded")
    page.wait_for_url("**/workspaces", timeout=15_000)
    return [
        Check(
            "no_membership.api",
            "PASS",
            "protected workspace API returned 403",
        ),
        Check(
            "no_membership.browser",
            "PASS",
            "protected members route redirected to /workspaces",
        ),
    ]


def _run_invalid_login(page: Page, web_url: str, run_id: str) -> Check:
    page.goto(f"{web_url}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_label("Work email").fill(f"invalid-{run_id}@example.invalid")
    page.get_by_label("Password").fill("not-a-real-staging-password")
    page.get_by_role("button", name="Sign in").click()
    alert = page.get_by_role("alert")
    alert.wait_for(state="visible", timeout=15_000)
    if not alert.inner_text().strip():
        raise RuntimeError("invalid login displayed an empty error")
    return Check("authentication.invalid_login", "PASS", "invalid login failed visibly")


def _run_owner_product_journey(
    *,
    context: BrowserContext,
    page: Page,
    web_url: str,
    workspace_id: str,
    email: str,
    password: str,
) -> list[Check]:
    _login(page, web_url, email, password)
    page.goto(f"{web_url}/workspace/{workspace_id}", wait_until="domcontentloaded")
    page.get_by_role("heading", name="Catalog intelligence").wait_for(
        state="visible", timeout=15_000
    )
    checks = [
        Check(
            "workspace.shell",
            "PASS",
            "deterministic QA workspace shell rendered",
        )
    ]

    page.goto(f"{web_url}/workspace/{workspace_id}/products", wait_until="domcontentloaded")
    page.get_by_text("Products", exact=True).first.wait_for(state="visible", timeout=20_000)
    checks.append(Check("catalog.products", "PASS", "product browser rendered"))

    page.goto(f"{web_url}/workspace/{workspace_id}/demo", wait_until="domcontentloaded")
    page.get_by_text("Presenter preflight", exact=False).first.wait_for(
        state="visible", timeout=20_000
    )
    checks.append(Check("demo.browser", "PASS", "client demo/preflight surface rendered"))

    page.goto(
        f"{web_url}/workspace/{workspace_id}/service-visibility",
        wait_until="domcontentloaded",
    )
    page.get_by_text("Service Visibility", exact=False).first.wait_for(
        state="visible", timeout=20_000
    )
    checks.append(
        Check(
            "service_visibility.browser",
            "PASS",
            "Service Visibility surface rendered",
        )
    )
    return checks


def _context(browser: Browser, playwright: Playwright, profile: str) -> BrowserContext:
    if profile == "mobile-chromium":
        device = dict(playwright.devices["Pixel 7"])
        return browser.new_context(**device)
    return browser.new_context(viewport={"width": 1440, "height": 900})


def main() -> int:
    report_path = Path(
        os.getenv("CATORA_STAGING_BROWSER_REPORT", "staging-browser-evidence.json")
    )
    started = int(time.time())
    run_id = os.getenv("CATORA_STAGING_QA_RUN_ID", "").strip() or str(started)
    checks: list[Check] = []
    decision = "FAILED"
    detail = "browser certification did not complete"

    try:
        web_url = _base_url("CATORA_STAGING_WEB_URL")
        api_url = _base_url("CATORA_STAGING_API_URL")
        workspace_id = _required("CATORA_STAGING_QA_WORKSPACE_ID")
        denied_workspace_id = _required("CATORA_STAGING_DENIED_WORKSPACE_ID")
        if denied_workspace_id == workspace_id:
            raise BlockedError("QA and denied workspace IDs must be different")

        credentials = {
            role: _credential(*env_names) for role, env_names in ROLE_ENV.items()
        }
        no_membership = _credential(*NO_MEMBERSHIP_ENV)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for profile in ("desktop-chromium", "mobile-chromium"):
                    invalid_context = _context(browser, playwright, profile)
                    try:
                        invalid_page = invalid_context.new_page()
                        check = _run_invalid_login(invalid_page, web_url, run_id)
                        checks.append(
                            Check(
                                f"{profile}.{check.name}",
                                check.status,
                                check.detail,
                            )
                        )
                    finally:
                        invalid_context.close()

                    for role, (email, password) in credentials.items():
                        context = _context(browser, playwright, profile)
                        console_errors = 0
                        try:
                            page = context.new_page()

                            def on_console(message: Any) -> None:
                                nonlocal console_errors
                                if getattr(message, "type", "") == "error":
                                    console_errors += 1

                            page.on("console", on_console)
                            role_checks = _run_role(
                                context=context,
                                page=page,
                                web_url=web_url,
                                api_url=api_url,
                                workspace_id=workspace_id,
                                denied_workspace_id=denied_workspace_id,
                                role=role,
                                email=email,
                                password=password,
                                run_id=run_id,
                            )
                            checks.extend(
                                Check(
                                    f"{profile}.{check.name}",
                                    check.status,
                                    check.detail,
                                )
                                for check in role_checks
                            )
                            checks.append(
                                Check(
                                    f"{profile}.{role}.console",
                                    "PASS" if console_errors == 0 else "FAIL",
                                    f"console error count={console_errors}",
                                )
                            )
                            if console_errors:
                                raise RuntimeError(
                                    f"{role}: observed {console_errors} browser console errors"
                                )
                        finally:
                            context.close()

                    context = _context(browser, playwright, profile)
                    try:
                        page = context.new_page()
                        no_member_checks = _run_no_membership(
                            context=context,
                            page=page,
                            web_url=web_url,
                            api_url=api_url,
                            workspace_id=workspace_id,
                            email=no_membership[0],
                            password=no_membership[1],
                        )
                        checks.extend(
                            Check(
                                f"{profile}.{check.name}",
                                check.status,
                                check.detail,
                            )
                            for check in no_member_checks
                        )
                    finally:
                        context.close()

                owner_context = _context(browser, playwright, "desktop-chromium")
                try:
                    owner_page = owner_context.new_page()
                    owner_journey = _run_owner_product_journey(
                        context=owner_context,
                        page=owner_page,
                        web_url=web_url,
                        workspace_id=workspace_id,
                        email=credentials["owner"][0],
                        password=credentials["owner"][1],
                    )
                    checks.extend(owner_journey)
                finally:
                    owner_context.close()
            finally:
                browser.close()

        decision = "PASS"
        detail = "mandatory browser and RBAC checks passed"
        exit_code = 0
    except BlockedError as exc:
        decision = "BLOCKED"
        detail = str(exc)
        exit_code = 2
    except Exception as exc:
        decision = "FAILED"
        detail = f"{type(exc).__name__}: {exc}"
        exit_code = 1

    report = {
        "schema": "catora-staging-browser-certification/v1",
        "qa_run_id": run_id,
        "started_at_unix": started,
        "decision": decision,
        "detail": detail,
        "checks": [asdict(check) for check in checks],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Browser certification: {decision}")
    print(detail)
    print(f"Sanitized evidence: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
