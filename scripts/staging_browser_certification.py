from __future__ import annotations

import json
import os
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
PROFILES = ("desktop-chromium", "mobile-chromium")


class BlockedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass(slots=True)
class BrowserSignals:
    console_errors: int = 0
    page_errors: int = 0
    failed_requests: int = 0
    server_errors: int = 0


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise BlockedError(f"Missing required staging configuration: {name}")
    return value


def _credential(email_name: str, password_name: str) -> tuple[str, str]:
    return _required(email_name), _required(password_name)


def _base_url(name: str) -> str:
    return _required(name).rstrip("/")


def _context(browser: Browser, playwright: Playwright, profile: str) -> BrowserContext:
    if profile == "mobile-chromium":
        device = dict(playwright.devices["Pixel 7"])
        return browser.new_context(**device)
    return browser.new_context(viewport={"width": 1440, "height": 900})


def _attach_quality_signals(page: Page, web_url: str) -> BrowserSignals:
    signals = BrowserSignals()

    def on_console(message: Any) -> None:
        if getattr(message, "type", "") == "error":
            signals.console_errors += 1

    def on_page_error(_: Any) -> None:
        signals.page_errors += 1

    def on_request_failed(request: Any) -> None:
        url = str(getattr(request, "url", ""))
        failure = getattr(request, "failure", None)
        if url.startswith(web_url) and failure and "ERR_ABORTED" not in str(failure):
            signals.failed_requests += 1

    def on_response(response: Any) -> None:
        url = str(getattr(response, "url", ""))
        status = int(getattr(response, "status", 0) or 0)
        if url.startswith(web_url) and status >= 500:
            signals.server_errors += 1

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)
    return signals


def _assert_quality(signals: BrowserSignals, prefix: str) -> list[Check]:
    checks = [
        Check(
            f"{prefix}.console",
            "PASS" if signals.console_errors == 0 else "FAIL",
            f"console error count={signals.console_errors}",
        ),
        Check(
            f"{prefix}.pageerror",
            "PASS" if signals.page_errors == 0 else "FAIL",
            f"uncaught page error count={signals.page_errors}",
        ),
        Check(
            f"{prefix}.requestfailed",
            "PASS" if signals.failed_requests == 0 else "FAIL",
            f"same-origin failed request count={signals.failed_requests}",
        ),
        Check(
            f"{prefix}.http5xx",
            "PASS" if signals.server_errors == 0 else "FAIL",
            f"same-origin HTTP 5xx count={signals.server_errors}",
        ),
    ]
    if any(
        (
            signals.console_errors,
            signals.page_errors,
            signals.failed_requests,
            signals.server_errors,
        )
    ):
        raise RuntimeError(
            f"{prefix}: browser quality errors "
            f"(console={signals.console_errors}, page={signals.page_errors}, "
            f"failed_requests={signals.failed_requests}, http5xx={signals.server_errors})"
        )
    return checks


def _assert_mobile_no_overflow(page: Page, label: str) -> Check:
    metrics = page.evaluate(
        """() => ({
          innerWidth: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
        })"""
    )
    if not isinstance(metrics, dict):
        raise RuntimeError(f"{label}: mobile overflow metrics were invalid")
    inner_width = int(metrics.get("innerWidth", 0))
    scroll_width = int(metrics.get("scrollWidth", 0))
    if scroll_width > inner_width + 2:
        raise RuntimeError(
            f"{label}: horizontal overflow detected ({scroll_width}px > {inner_width}px)"
        )
    return Check(
        f"mobile.layout.{label}",
        "PASS",
        f"no horizontal overflow ({scroll_width}px <= {inner_width}px)",
    )


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


def _run_unauthenticated_guard(
    page: Page,
    web_url: str,
    workspace_id: str,
) -> list[Check]:
    page.goto(
        f"{web_url}/workspace/{workspace_id}/members",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.wait_for_url("**/login", timeout=15_000)
    page.get_by_role(
        "heading", name="Sign in to your commerce intelligence workspace."
    ).wait_for(state="visible", timeout=15_000)
    return [
        Check(
            "authentication.protected_route",
            "PASS",
            "unauthenticated protected workspace route redirected to /login",
        )
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
    if "/login" not in page.url:
        raise RuntimeError("invalid login navigated away from /login")
    return Check(
        "authentication.invalid_login",
        "PASS",
        "invalid login failed visibly without creating a session",
    )


def _run_setup_form_contract(page: Page, web_url: str) -> list[Check]:
    page.goto(f"{web_url}/setup", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_role("heading", name="Create the first protected workspace.").wait_for(
        state="visible", timeout=15_000
    )
    expected_labels = (
        "Organization name",
        "Organization slug",
        "Workspace name",
        "Workspace slug",
        "Owner name",
        "Owner email",
        "Password",
    )
    for label in expected_labels:
        page.get_by_label(label).wait_for(state="visible", timeout=10_000)
    slug = page.get_by_label("Organization slug")
    slug.fill("INVALID SLUG")
    if slug.evaluate("(element) => element.checkValidity()"):
        raise RuntimeError("setup form accepted an invalid organization slug")
    slug.fill("")
    return [
        Check(
            "authentication.setup_contract",
            "PASS",
            "first-run setup exposes required fields and browser-side slug validation",
        )
    ]


def _run_forgot_password_enumeration(
    page: Page,
    web_url: str,
    known_email: str,
    run_id: str,
) -> Check:
    messages: list[str] = []
    for email in (known_email, f"unknown-{run_id}@example.invalid"):
        page.goto(
            f"{web_url}/forgot-password",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.get_by_role("heading", name="Reset your password").wait_for(
            state="visible", timeout=15_000
        )
        page.get_by_label("Work email").fill(email)
        page.get_by_role("button", name="Send reset link").click()
        message = page.get_by_text(
            "Check your email if an active account exists.", exact=True
        )
        message.wait_for(state="visible", timeout=15_000)
        messages.append(message.inner_text().strip())
    if len(set(messages)) != 1:
        raise RuntimeError("forgot-password response differs for known and unknown accounts")
    return Check(
        "authentication.forgot_password_enumeration",
        "PASS",
        "known and unknown accounts receive the same browser response",
    )


def _run_token_fail_closed(page: Page, web_url: str, run_id: str) -> list[Check]:
    checks: list[Check] = []

    page.goto(f"{web_url}/reset-password", wait_until="domcontentloaded", timeout=30_000)
    reset_button = page.get_by_role("button", name="Reset password")
    if reset_button.is_enabled():
        raise RuntimeError("password reset is enabled without a token")
    checks.append(
        Check(
            "authentication.reset_missing_token",
            "PASS",
            "password reset remains disabled when the token is missing",
        )
    )

    page.goto(
        f"{web_url}/reset-password?token=invalid-{run_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_label("New password").fill("Staging-only-invalid-password-123")
    page.get_by_role("button", name="Reset password").click()
    page.get_by_role("alert").wait_for(state="visible", timeout=15_000)
    if "/reset-password" not in page.url:
        raise RuntimeError("invalid password-reset token unexpectedly navigated away")
    checks.append(
        Check(
            "authentication.reset_invalid_token",
            "PASS",
            "invalid password-reset token failed closed with a visible error",
        )
    )

    page.goto(
        f"{web_url}/accept-invitation",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    invite_button = page.get_by_role("button", name="Accept invitation")
    if invite_button.is_enabled():
        raise RuntimeError("invitation acceptance is enabled without a token")
    checks.append(
        Check(
            "authentication.invitation_missing_token",
            "PASS",
            "invitation acceptance remains disabled when the token is missing",
        )
    )

    page.goto(
        f"{web_url}/accept-invitation?token=invalid-{run_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_label("Display name").fill("Invalid Invite Test")
    page.get_by_label("New password").fill("Staging-only-invalid-password-123")
    page.get_by_role("button", name="Accept invitation").click()
    page.get_by_role("alert").wait_for(state="visible", timeout=15_000)
    if "/accept-invitation" not in page.url:
        raise RuntimeError("invalid invitation token unexpectedly navigated away")
    checks.append(
        Check(
            "authentication.invitation_invalid_token",
            "PASS",
            "invalid invitation token failed closed with a visible error",
        )
    )
    return checks


def _run_public_auth_suite(
    page: Page,
    web_url: str,
    workspace_id: str,
    owner_email: str,
    run_id: str,
) -> list[Check]:
    checks = _run_unauthenticated_guard(page, web_url, workspace_id)
    checks.append(_run_invalid_login(page, web_url, run_id))
    checks.extend(_run_setup_form_contract(page, web_url))
    checks.append(
        _run_forgot_password_enumeration(page, web_url, owner_email, run_id)
    )
    checks.extend(_run_token_fail_closed(page, web_url, run_id))
    return checks


def _assert_workspace_selector(
    page: Page,
    workspace_id: str,
    denied_workspace_id: str,
    role: str,
) -> Check:
    qa_card = page.locator(f'a[href="/workspace/{workspace_id}"]')
    qa_card.wait_for(state="visible", timeout=15_000)
    actual_role = qa_card.locator("small").inner_text().strip()
    if actual_role != role:
        raise RuntimeError(
            f"{role}: workspace selector showed role {actual_role!r}, expected {role!r}"
        )
    if page.locator(f'a[href="/workspace/{denied_workspace_id}"]').count() != 0:
        raise RuntimeError(f"{role}: denied workspace leaked into workspace selector")
    return Check(
        f"{role}.workspace_selector",
        "PASS",
        "QA workspace is visible with the exact role and denied workspace is absent",
    )


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
    checks.append(
        _assert_workspace_selector(page, workspace_id, denied_workspace_id, role)
    )

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

    page.goto(
        f"{web_url}/workspace/{workspace_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Catalog intelligence").wait_for(
        state="visible", timeout=15_000
    )
    for link_name in (
        "Add or explore a catalog",
        "Launch client demo",
        "Browse products",
        "Audit a service website",
        "Review identities",
        "Manage access",
    ):
        page.get_by_role("link", name=link_name).wait_for(
            state="visible", timeout=10_000
        )
    checks.append(
        Check(
            f"{role}.workspace_shell",
            "PASS",
            "workspace shell and primary navigation rendered",
        )
    )

    page.goto(
        f"{web_url}/workspace/{workspace_id}/members",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
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
        denied_invite = context.request.post(
            f"{api_url}/api/v1/workspaces/{workspace_id}/invitations",
            data={
                "email": f"qa-denied-{run_id}@example.invalid",
                "role": "viewer",
            },
            headers=_direct_api_headers(context, web_url, include_csrf=True),
            timeout=15_000,
        )
        if denied_invite.status != 403:
            raise RuntimeError(
                f"{role}: prohibited invitation mutation returned HTTP "
                f"{denied_invite.status}, expected 403"
            )
        checks.append(
            Check(
                f"{role}.member_manage_api",
                "PASS",
                "prohibited invitation mutation returned 403",
            )
        )

    page.goto(
        f"{web_url}/workspace/{workspace_id}/identity-review",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Duplicate candidates").wait_for(
        state="visible", timeout=20_000
    )
    refresh_button = page.get_by_role("button", name="Refresh candidates")
    if role in {"owner", "admin"}:
        refresh_button.wait_for(state="visible", timeout=10_000)
        checks.append(
            Check(
                f"{role}.identity_manage_ui",
                "PASS",
                "identity-management refresh control is available",
            )
        )
    else:
        page.get_by_text(
            "Only owners and admins can link or reject identities.", exact=False
        ).wait_for(state="visible", timeout=10_000)
        if refresh_button.count() != 0:
            raise RuntimeError(f"{role}: identity-management controls leaked into the UI")
        denied_refresh = context.request.post(
            f"{api_url}/api/v1/workspaces/{workspace_id}/identity-candidates/refresh",
            headers=_direct_api_headers(context, web_url, include_csrf=True),
            timeout=15_000,
        )
        if denied_refresh.status != 403:
            raise RuntimeError(
                f"{role}: prohibited identity refresh returned HTTP "
                f"{denied_refresh.status}, expected 403"
            )
        checks.append(
            Check(
                f"{role}.identity_manage_api",
                "PASS",
                "prohibited identity refresh returned 403",
            )
        )

    page.goto(
        f"{web_url}/workspace/{workspace_id}/demo",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("navigation", name="Demo steps").wait_for(
        state="visible", timeout=20_000
    )
    readiness = page.get_by_role("heading", name="Demo readiness")
    if role in {"owner", "admin"}:
        readiness.wait_for(state="visible", timeout=20_000)
        checks.append(
            Check(
                f"{role}.presenter_controls",
                "PASS",
                "presenter-only demo readiness controls are visible",
            )
        )
    else:
        readiness.wait_for(state="hidden", timeout=15_000)
        if readiness.count() != 0:
            raise RuntimeError(f"{role}: presenter-only controls leaked into the UI")
        checks.append(
            Check(
                f"{role}.presenter_controls",
                "PASS",
                "presenter-only demo controls are absent",
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
            f"{role}.cross_workspace_api",
            "PASS",
            "cross-workspace member request returned 403",
        )
    )

    page.goto(
        f"{web_url}/workspace/{denied_workspace_id}/members",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.wait_for_url("**/workspaces", timeout=15_000)
    checks.append(
        Check(
            f"{role}.cross_workspace_browser",
            "PASS",
            "direct denied-workspace browser route returned to /workspaces",
        )
    )

    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url("**/login", timeout=15_000)
    after_logout = context.request.get(
        f"{api_url}/api/v1/auth/me",
        headers=direct_headers,
        timeout=15_000,
    )
    if after_logout.status != 401:
        raise RuntimeError(
            f"{role}: revoked session returned HTTP {after_logout.status} "
            "after logout, expected 401"
        )
    checks.append(
        Check(
            f"{role}.logout",
            "PASS",
            "pre-logout session token was revoked server-side",
        )
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
    page.get_by_text("No active workspace memberships.", exact=True).wait_for(
        state="visible", timeout=10_000
    )
    if page.locator(f'a[href="/workspace/{workspace_id}"]').count() != 0:
        raise RuntimeError("no-membership identity can see the QA workspace card")

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

    page.goto(
        f"{web_url}/workspace/{workspace_id}/members",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.wait_for_url("**/workspaces", timeout=15_000)
    return [
        Check(
            "no_membership.selector",
            "PASS",
            "workspace selector reports no memberships and exposes no QA workspace card",
        ),
        Check(
            "no_membership.api",
            "PASS",
            "protected workspace API returned 403",
        ),
        Check(
            "no_membership.browser",
            "PASS",
            "protected workspace browser route redirected to /workspaces",
        ),
    ]


def _wait_catalog_idle(page: Page) -> None:
    page.wait_for_function(
        """() => {
          const panel = document.querySelector('.catalog-panel');
          return panel && panel.getAttribute('aria-busy') === 'false';
        }""",
        timeout=20_000,
    )


def _run_catalog_journey(
    page: Page,
    web_url: str,
    workspace_id: str,
) -> list[Check]:
    checks: list[Check] = []
    page.goto(
        f"{web_url}/workspace/{workspace_id}/products",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Products").wait_for(
        state="visible", timeout=20_000
    )
    _wait_catalog_idle(page)
    rows = page.locator(".product-row")
    if rows.count() < 1:
        raise RuntimeError("deterministic QA catalog rendered no product rows")
    first_title = rows.first.locator(".product-title-cell strong").inner_text().strip()
    if not first_title:
        raise RuntimeError("first product row has no title")
    checks.append(
        Check(
            "catalog.list",
            "PASS",
            "deterministic QA product list rendered at least one product",
        )
    )

    search = page.get_by_label("Search products")
    search.fill(first_title)
    page.get_by_role("button", name="Search").click()
    _wait_catalog_idle(page)
    if page.locator(".product-row").count() < 1:
        raise RuntimeError("exact-title product search returned no results")
    checks.append(
        Check(
            "catalog.search",
            "PASS",
            "exact-title product search returned a product",
        )
    )

    search.fill("")
    page.get_by_role("button", name="Search").click()
    _wait_catalog_idle(page)

    warning_filter = page.get_by_label("Filter by normalization state")
    warning_filter.select_option("warnings")
    _wait_catalog_idle(page)
    warning_rows = page.locator(".product-row")
    if warning_rows.count() < 1:
        raise RuntimeError("warning filter returned no deterministic QA products")
    for index in range(min(warning_rows.count(), 10)):
        pill = warning_rows.nth(index).locator(".warning-pill")
        if pill.count() != 1:
            raise RuntimeError("warning filter returned a row without a warning pill")
    checks.append(
        Check(
            "catalog.warning_filter",
            "PASS",
            "needs-review filter returned warning-marked products",
        )
    )

    warning_filter.select_option("clean")
    _wait_catalog_idle(page)
    clean_rows = page.locator(".product-row")
    if clean_rows.count() < 1:
        raise RuntimeError("clean filter returned no deterministic QA products")
    for index in range(min(clean_rows.count(), 10)):
        pill = clean_rows.nth(index).locator(".clean-pill")
        if pill.count() != 1:
            raise RuntimeError("clean filter returned a row without a clean pill")
    checks.append(
        Check(
            "catalog.clean_filter",
            "PASS",
            "no-warning filter returned clean-marked products",
        )
    )

    warning_filter.select_option("all")
    _wait_catalog_idle(page)
    next_button = page.get_by_role("button", name="Next")
    if not next_button.is_enabled():
        raise RuntimeError("deterministic QA catalog does not expose a second page")
    next_button.click()
    _wait_catalog_idle(page)
    summary = page.locator(".catalog-summary span").nth(1).inner_text()
    if not summary.startswith("26"):
        raise RuntimeError(f"catalog pagination did not advance to row 26: {summary!r}")
    page.get_by_role("button", name="Previous").click()
    _wait_catalog_idle(page)
    checks.append(
        Check(
            "catalog.pagination",
            "PASS",
            "catalog advanced to the second page and returned to the first",
        )
    )

    first_row = page.locator(".product-row").first
    href = first_row.get_attribute("href")
    if not href or not href.startswith(f"/workspace/{workspace_id}/products/"):
        raise RuntimeError("first product row has no valid product-detail link")
    first_row.click()
    page.wait_for_url(f"**{href}", timeout=15_000)
    page.get_by_role("region", name="Product summary").wait_for(
        state="visible", timeout=20_000
    )
    for heading in ("Product attributes", "Variants", "Source provenance"):
        page.get_by_role("heading", name=heading).wait_for(
            state="visible", timeout=15_000
        )
    checks.append(
        Check(
            "catalog.product_detail",
            "PASS",
            "product detail rendered summary, attributes, variants and source provenance",
        )
    )
    return checks


def _run_demo_journey(page: Page, web_url: str, workspace_id: str) -> list[Check]:
    page.goto(
        f"{web_url}/workspace/{workspace_id}/demo",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("navigation", name="Demo steps").wait_for(
        state="visible", timeout=20_000
    )
    readiness = page.get_by_role("heading", name="Demo readiness")
    readiness.wait_for(state="visible", timeout=20_000)
    status = page.get_by_text("Ready to present", exact=True)
    fallback = page.get_by_text("Using verified fallback", exact=True)
    if status.count() == 0 and fallback.count() == 0:
        raise RuntimeError("presenter preflight produced no explicit readiness state")
    page.get_by_text("1,000 products", exact=False).first.wait_for(
        state="visible", timeout=20_000
    )
    page.get_by_role("link", name="Download executive PPTX").wait_for(
        state="visible", timeout=10_000
    )
    return [
        Check(
            "demo.client_story",
            "PASS",
            "client demo navigation and deterministic catalog evidence rendered",
        ),
        Check(
            "demo.presenter_preflight",
            "PASS",
            "presenter preflight exposed an explicit ready/fallback state",
        ),
        Check(
            "demo.report_link",
            "PASS",
            "executive PPTX download link is present",
        ),
    ]


def _run_identity_review_journey(
    page: Page,
    web_url: str,
    workspace_id: str,
) -> list[Check]:
    page.goto(
        f"{web_url}/workspace/{workspace_id}/identity-review",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Duplicate candidates").wait_for(
        state="visible", timeout=20_000
    )
    page.get_by_text("Algorithmic suggestions only", exact=True).wait_for(
        state="visible", timeout=15_000
    )
    page.get_by_role("button", name="Refresh candidates").wait_for(
        state="visible", timeout=10_000
    )
    return [
        Check(
            "identity_review.queue",
            "PASS",
            "identity review queue rendered evidence-first owner controls without mutating data",
        )
    ]


def _run_onboarding_contract(
    page: Page,
    web_url: str,
    workspace_id: str,
) -> list[Check]:
    page.goto(
        f"{web_url}/workspace/{workspace_id}/onboarding",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Bring a catalog into Catora").wait_for(
        state="visible", timeout=20_000
    )
    for heading in ("Explore sample catalog", "Upload Shopify CSV"):
        page.get_by_role("heading", name=heading).wait_for(
            state="visible", timeout=10_000
        )
    submit = page.get_by_role("button", name="Upload and run full assessment")
    if submit.is_enabled():
        raise RuntimeError("prospect diagnostic can start without authorization and a file")
    authorization = page.get_by_text(
        "I confirm the prospect has authorized this catalog diagnostic", exact=False
    )
    authorization.wait_for(state="visible", timeout=10_000)
    file_input = page.locator('input[type="file"]')
    accept = file_input.get_attribute("accept") or ""
    if ".csv" not in accept:
        raise RuntimeError("prospect diagnostic file input does not constrain CSV input")
    return [
        Check(
            "onboarding.paths",
            "PASS",
            "sample and prospect-diagnostic onboarding paths rendered",
        ),
        Check(
            "onboarding.authorization_gate",
            "PASS",
            "diagnostic submission is disabled before explicit authorization/file selection",
        ),
        Check(
            "onboarding.csv_contract",
            "PASS",
            "catalog upload input advertises CSV-only source types",
        ),
    ]


def _first_ingestion_job_id(
    context: BrowserContext,
    web_url: str,
    api_url: str,
    workspace_id: str,
) -> str:
    response = context.request.get(
        f"{api_url}/api/v1/workspaces/{workspace_id}/ingestion-jobs",
        headers=_direct_api_headers(context, web_url),
        timeout=15_000,
    )
    if response.status != 200:
        raise RuntimeError(
            f"ingestion job lookup returned HTTP {response.status}, expected 200"
        )
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("deterministic QA workspace has no ingestion job")
    job_id = payload[0].get("id") if isinstance(payload[0], dict) else None
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("deterministic QA ingestion job has no ID")
    return job_id


def _run_processing_journey(
    context: BrowserContext,
    page: Page,
    web_url: str,
    api_url: str,
    workspace_id: str,
) -> list[Check]:
    job_id = _first_ingestion_job_id(
        context, web_url, api_url, workspace_id
    )
    page.goto(
        f"{web_url}/workspace/{workspace_id}/processing/{job_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    heading = page.locator("h1")
    heading.wait_for(state="visible", timeout=15_000)
    if heading.inner_text().strip() not in {
        "Your catalog is ready",
        "Catora is preparing your catalog",
    }:
        raise RuntimeError("processing page rendered an unexpected state heading")
    page.get_by_role("region", name="Import counts").wait_for(
        state="visible", timeout=10_000
    )
    page.get_by_role("region", name="Catalog processing stages").wait_for(
        state="visible", timeout=10_000
    )
    page.get_by_role("heading", name="Uploading catalog").wait_for(
        state="visible", timeout=10_000
    )
    return [
        Check(
            "processing.persisted_status",
            "PASS",
            "processing journey rendered persisted import counts and stage state",
        )
    ]


def _run_service_visibility_contract(
    page: Page,
    web_url: str,
    workspace_id: str,
) -> list[Check]:
    page.goto(
        f"{web_url}/workspace/{workspace_id}/service-visibility",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role(
        "heading", name="Audit services for search and answer readiness"
    ).wait_for(state="visible", timeout=20_000)
    page.get_by_role("heading", name="Add a service website").wait_for(
        state="visible", timeout=10_000
    )
    create = page.get_by_role("button", name="Create source")
    if create.is_enabled():
        raise RuntimeError("Service Visibility source creation is enabled before authorization")
    page.get_by_text(
        "I confirm authorization to audit this public domain.", exact=False
    ).wait_for(state="visible", timeout=10_000)
    page.get_by_role("heading", name="Configured sources").wait_for(
        state="visible", timeout=10_000
    )
    page.get_by_role("heading", name="Audit runs").wait_for(
        state="visible", timeout=10_000
    )
    page.get_by_role(
        "heading", name="Connect Search Console and GA4"
    ).wait_for(state="visible", timeout=15_000)
    credential = page.get_by_label("Railway credential reference")
    if credential.input_value() != "env:CATORA_GOOGLE_MEASUREMENT_SERVICE_ACCOUNT_JSON":
        raise RuntimeError("Google measurement UI does not use the managed env reference default")
    return [
        Check(
            "service_visibility.authorization_gate",
            "PASS",
            "source creation remains disabled before explicit domain authorization",
        ),
        Check(
            "service_visibility.read_surfaces",
            "PASS",
            "configured-source and audit-run surfaces rendered",
        ),
        Check(
            "measurement.managed_credential_reference",
            "PASS",
            "Google measurement uses a managed environment credential reference, not raw JSON",
        ),
    ]


def _run_owner_journeys(
    *,
    context: BrowserContext,
    page: Page,
    web_url: str,
    api_url: str,
    workspace_id: str,
    email: str,
    password: str,
    profile: str,
) -> list[Check]:
    _login(page, web_url, email, password)
    checks: list[Check] = []

    page.goto(
        f"{web_url}/workspace/{workspace_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    page.get_by_role("heading", name="Catalog intelligence").wait_for(
        state="visible", timeout=15_000
    )
    checks.append(
        Check(
            "workspace.shell",
            "PASS",
            "deterministic QA workspace shell rendered",
        )
    )
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "workspace"))

    checks.extend(_run_catalog_journey(page, web_url, workspace_id))
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "product_detail"))

    checks.extend(_run_demo_journey(page, web_url, workspace_id))
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "demo"))

    checks.extend(_run_identity_review_journey(page, web_url, workspace_id))
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "identity_review"))

    checks.extend(_run_onboarding_contract(page, web_url, workspace_id))
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "onboarding"))

    checks.extend(
        _run_processing_journey(
            context, page, web_url, api_url, workspace_id
        )
    )

    checks.extend(_run_service_visibility_contract(page, web_url, workspace_id))
    if profile == "mobile-chromium":
        checks.append(_assert_mobile_no_overflow(page, "service_visibility"))

    return checks


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
                for profile in PROFILES:
                    public_context = _context(browser, playwright, profile)
                    try:
                        public_page = public_context.new_page()
                        public_signals = _attach_quality_signals(public_page, web_url)
                        profile_checks = _run_public_auth_suite(
                            public_page,
                            web_url,
                            workspace_id,
                            credentials["owner"][0],
                            run_id,
                        )
                        checks.extend(
                            Check(
                                f"{profile}.{check.name}",
                                check.status,
                                check.detail,
                            )
                            for check in profile_checks
                        )
                        if profile == "mobile-chromium":
                            public_page.goto(
                                f"{web_url}/login",
                                wait_until="domcontentloaded",
                                timeout=30_000,
                            )
                            checks.append(
                                _assert_mobile_no_overflow(public_page, "login")
                            )
                        checks.extend(
                            _assert_quality(public_signals, f"{profile}.public")
                        )
                    finally:
                        public_context.close()

                    for role, (email, password) in credentials.items():
                        context = _context(browser, playwright, profile)
                        try:
                            page = context.new_page()
                            signals = _attach_quality_signals(page, web_url)
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
                            checks.extend(
                                _assert_quality(
                                    signals,
                                    f"{profile}.{role}.quality",
                                )
                            )
                        finally:
                            context.close()

                    no_member_context = _context(browser, playwright, profile)
                    try:
                        no_member_page = no_member_context.new_page()
                        signals = _attach_quality_signals(
                            no_member_page, web_url
                        )
                        no_member_checks = _run_no_membership(
                            context=no_member_context,
                            page=no_member_page,
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
                        checks.extend(
                            _assert_quality(
                                signals,
                                f"{profile}.no_membership.quality",
                            )
                        )
                    finally:
                        no_member_context.close()

                    owner_context = _context(browser, playwright, profile)
                    try:
                        owner_page = owner_context.new_page()
                        signals = _attach_quality_signals(owner_page, web_url)
                        owner_checks = _run_owner_journeys(
                            context=owner_context,
                            page=owner_page,
                            web_url=web_url,
                            api_url=api_url,
                            workspace_id=workspace_id,
                            email=credentials["owner"][0],
                            password=credentials["owner"][1],
                            profile=profile,
                        )
                        checks.extend(
                            Check(
                                f"{profile}.{check.name}",
                                check.status,
                                check.detail,
                            )
                            for check in owner_checks
                        )
                        checks.extend(
                            _assert_quality(
                                signals,
                                f"{profile}.owner_journeys.quality",
                            )
                        )
                    finally:
                        owner_context.close()
            finally:
                browser.close()

        decision = "PASS"
        detail = (
            "mandatory desktop/mobile authentication, session, RBAC, isolation, "
            "catalog, demo, identity review, onboarding, processing, Service Visibility, "
            "measurement and browser-quality checks passed"
        )
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
        "schema": "catora-staging-browser-certification/v2",
        "qa_run_id": run_id,
        "started_at_unix": started,
        "decision": decision,
        "detail": detail,
        "check_count": len(checks),
        "checks": [asdict(check) for check in checks],
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Browser certification: {decision}")
    print(detail)
    print(f"Sanitized evidence: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
