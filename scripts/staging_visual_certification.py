from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


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


def _context(browser: Browser, playwright: Playwright, profile: str) -> BrowserContext:
    if profile == "mobile-chromium":
        return browser.new_context(**dict(playwright.devices["Pixel 7"]))
    return browser.new_context(viewport={"width": 1440, "height": 900})


def _settle(page: Page) -> None:
    page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
    page.wait_for_timeout(250)


def _login(page: Page, web_url: str, email: str, password: str) -> None:
    page.get_by_label("Work email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/workspaces", timeout=20_000)
    page.get_by_role("button", name="Sign out").wait_for(state="visible", timeout=15_000)


def _changed_pixel_ratio(baseline_path: Path, candidate_path: Path) -> float:
    with Image.open(baseline_path) as baseline_source, Image.open(candidate_path) as candidate_source:
        baseline = baseline_source.convert("RGB")
        candidate = candidate_source.convert("RGB")
        if baseline.size != candidate.size:
            return 1.0
        difference = ImageChops.difference(baseline, candidate)
        red, green, blue = difference.split()
        mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        histogram = mask.histogram()
        total_pixels = baseline.width * baseline.height
        unchanged = histogram[0] if histogram else 0
        return (total_pixels - unchanged) / total_pixels if total_pixels else 1.0


def _capture(
    *,
    page: Page,
    profile: str,
    name: str,
    baseline_root: Path,
    candidate_root: Path,
    max_changed_ratio: float,
) -> Check:
    candidate_path = candidate_root / profile / f"{name}.png"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(candidate_path), full_page=True, animations="disabled")
    baseline_path = baseline_root / profile / f"{name}.png"
    if not baseline_path.exists():
        return Check(
            f"visual.{profile}.{name}",
            "BLOCKED",
            f"approved baseline missing: {baseline_path.as_posix()}",
        )
    ratio = _changed_pixel_ratio(baseline_path, candidate_path)
    if ratio > max_changed_ratio:
        return Check(
            f"visual.{profile}.{name}",
            "VISUAL REVIEW REQUIRED",
            f"changed pixel ratio {ratio:.6f} exceeds {max_changed_ratio:.6f}",
        )
    return Check(
        f"visual.{profile}.{name}",
        "PASS",
        f"changed pixel ratio {ratio:.6f}",
    )


def _profile(
    *,
    context: BrowserContext,
    profile: str,
    web_url: str,
    workspace_id: str,
    email: str,
    password: str,
    baseline_root: Path,
    candidate_root: Path,
    max_changed_ratio: float,
) -> list[Check]:
    page = context.new_page()
    checks: list[Check] = []

    page.goto(f"{web_url}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_role(
        "heading", name="Sign in to your commerce intelligence workspace."
    ).wait_for(state="visible", timeout=15_000)
    _settle(page)
    checks.append(
        _capture(
            page=page,
            profile=profile,
            name="login",
            baseline_root=baseline_root,
            candidate_root=candidate_root,
            max_changed_ratio=max_changed_ratio,
        )
    )

    _login(page, web_url, email, password)
    page.goto(f"{web_url}/workspace/{workspace_id}", wait_until="domcontentloaded")
    page.get_by_role("heading", name="Catalog intelligence").wait_for(
        state="visible", timeout=15_000
    )
    _settle(page)
    checks.append(
        _capture(
            page=page,
            profile=profile,
            name="workspace",
            baseline_root=baseline_root,
            candidate_root=candidate_root,
            max_changed_ratio=max_changed_ratio,
        )
    )

    page.goto(f"{web_url}/workspace/{workspace_id}/products", wait_until="domcontentloaded")
    page.get_by_text("Products", exact=True).first.wait_for(state="visible", timeout=20_000)
    _settle(page)
    checks.append(
        _capture(
            page=page,
            profile=profile,
            name="products",
            baseline_root=baseline_root,
            candidate_root=candidate_root,
            max_changed_ratio=max_changed_ratio,
        )
    )

    page.goto(
        f"{web_url}/workspace/{workspace_id}/service-visibility",
        wait_until="domcontentloaded",
    )
    page.get_by_text("Service Visibility", exact=False).first.wait_for(
        state="visible", timeout=20_000
    )
    _settle(page)
    checks.append(
        _capture(
            page=page,
            profile=profile,
            name="service-visibility",
            baseline_root=baseline_root,
            candidate_root=candidate_root,
            max_changed_ratio=max_changed_ratio,
        )
    )
    return checks


def main() -> int:
    started = int(time.time())
    report_path = Path(
        os.getenv("CATORA_STAGING_VISUAL_REPORT", "staging-visual-evidence.json")
    )
    candidate_root = report_path.parent / "visual-candidates"
    checks: list[Check] = []
    decision = "FAILED"
    detail = "visual certification did not complete"

    try:
        web_url = _required("CATORA_STAGING_WEB_URL").rstrip("/")
        workspace_id = _required("CATORA_STAGING_QA_WORKSPACE_ID")
        email = _required("CATORA_STAGING_OWNER_EMAIL")
        password = _required("CATORA_STAGING_OWNER_PASSWORD")
        baseline_root = Path(
            os.getenv("CATORA_STAGING_VISUAL_BASELINE_DIR", "qa/visual-baselines")
        )
        ratio_value = os.getenv(
            "CATORA_STAGING_VISUAL_MAX_CHANGED_PIXEL_RATIO", "0.002"
        ).strip()
        try:
            max_changed_ratio = float(ratio_value)
        except ValueError as exc:
            raise BlockedError(
                "CATORA_STAGING_VISUAL_MAX_CHANGED_PIXEL_RATIO must be numeric"
            ) from exc
        if not 0 <= max_changed_ratio <= 1:
            raise BlockedError(
                "CATORA_STAGING_VISUAL_MAX_CHANGED_PIXEL_RATIO must be between 0 and 1"
            )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for profile in ("desktop-chromium", "mobile-chromium"):
                    context = _context(browser, playwright, profile)
                    try:
                        checks.extend(
                            _profile(
                                context=context,
                                profile=profile,
                                web_url=web_url,
                                workspace_id=workspace_id,
                                email=email,
                                password=password,
                                baseline_root=baseline_root,
                                candidate_root=candidate_root,
                                max_changed_ratio=max_changed_ratio,
                            )
                        )
                    finally:
                        context.close()
            finally:
                browser.close()

        blocked = [check for check in checks if check.status == "BLOCKED"]
        review = [
            check for check in checks if check.status == "VISUAL REVIEW REQUIRED"
        ]
        if blocked:
            decision = "BLOCKED"
            detail = f"{len(blocked)} approved visual baselines are missing"
            exit_code = 2
        elif review:
            decision = "BLOCKED"
            detail = f"VISUAL REVIEW REQUIRED — {len(review)} material screenshot differences"
            exit_code = 2
        else:
            decision = "PASS"
            detail = "all approved visual baselines matched within tolerance"
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
        "schema": "catora-staging-visual-certification/v1",
        "timestamp_unix": started,
        "decision": decision,
        "detail": detail,
        "checks": [asdict(check) for check in checks],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Visual certification: {decision}")
    print(detail)
    print(f"Sanitized evidence: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
