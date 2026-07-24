from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


class AcceptanceError(RuntimeError):
    pass


def _origin(value: str, *, label: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AcceptanceError(f"{label} must be an HTTPS origin")
    return normalized


def _shop_domain(value: str) -> str:
    normalized = value.strip().casefold()
    if (
        not normalized.endswith(".myshopify.com")
        or "/" in normalized
        or ":" in normalized
        or normalized.startswith(".")
    ):
        raise AcceptanceError(
            "Shop domain must use its permanent *.myshopify.com hostname"
        )
    return normalized


def _enabled(value: str | None, *, label: str) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized in {"", "0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    raise AcceptanceError(f"{label} must be true or false")


def _json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} did not return a JSON object")
    return value


def _request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes, dict[str, str]]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), {
                key.casefold(): value for key, value in response.headers.items()
            }
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        detail = payload.decode(errors="replace")
        raise AcceptanceError(
            f"{method} {url} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AcceptanceError(f"{method} {url} could not be reached: {exc.reason}") from exc


def _bearer_request(
    app_url: str,
    path: str,
    session_token: str,
    *,
    method: str = "GET",
) -> dict[str, Any]:
    _, payload, _ = _request(
        f"{app_url}{path}",
        method=method,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    return _json(payload, label=path)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _signed_webhook(
    api_url: str,
    path: str,
    *,
    topic: str,
    shop_domain: str,
    secret: str,
    body: dict[str, object],
) -> dict[str, Any]:
    payload = json.dumps(body, separators=(",", ":")).encode()
    webhook_id = str(uuid.uuid4())
    _, response, _ = _request(
        f"{api_url}{path}",
        method="POST",
        body=payload,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Webhook-Id": webhook_id,
            "X-Shopify-Hmac-Sha256": _sign(payload, secret),
            "X-Shopify-Triggered-At": "2026-07-24T00:00:00Z",
        },
    )
    result = _json(response, label=f"Shopify {topic} webhook")
    result.pop("delivery_id", None)
    return {"accepted": True, "duplicate": result.get("duplicate") is True}


def _contains_forbidden_key(value: object) -> str | None:
    forbidden = {
        "access_token",
        "refresh_token",
        "encrypted_access_token",
        "encrypted_refresh_token",
        "client_secret",
        "password",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in forbidden:
                return str(key)
            found = _contains_forbidden_key(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _contains_forbidden_key(item)
            if found is not None:
                return found
    return None


def _nonnegative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise AcceptanceError(f"Installation status is missing a valid {key}")
    return item


def _validate_app_home(
    app_url: str,
    *,
    expected_api_key: str | None,
) -> dict[str, object]:
    status, payload, headers = _request(
        f"{app_url}/",
        headers={"Accept": "text/html"},
    )
    html = payload.decode("utf-8", errors="replace")
    if status != 200:
        raise AcceptanceError(f"App Home returned HTTP {status}")
    required = (
        'name="shopify-api-key"',
        "https://cdn.shopify.com/shopifycloud/app-bridge.js",
        "https://cdn.shopify.com/shopifycloud/polaris.js",
        "Catora Catalog Intelligence",
    )
    missing = [marker for marker in required if marker not in html]
    if missing:
        raise AcceptanceError(
            "App Home is missing required embedded markers: " + ", ".join(missing)
        )
    if "development-unlinked" in html or "__SHOPIFY_API_KEY__" in html:
        raise AcceptanceError("App Home was deployed without a linked Shopify API key")
    if expected_api_key and f'content="{expected_api_key}"' not in html:
        raise AcceptanceError("App Home does not contain the expected public app client ID")

    csp = headers.get("content-security-policy", "")
    if "frame-ancestors" not in csp or "admin.shopify.com" not in csp:
        raise AcceptanceError("App Home CSP does not permit Shopify Admin framing")
    if headers.get("x-frame-options", "").casefold() in {"deny", "sameorigin"}:
        raise AcceptanceError("App Home X-Frame-Options blocks Shopify Admin framing")
    return {
        "status": status,
        "app_bridge": True,
        "polaris": True,
        "shopify_api_key_linked": True,
        "frame_policy": "ok",
        "content_type": headers.get("content-type"),
    }


def _validate_readiness(api_url: str) -> dict[str, Any]:
    status, payload, _ = _request(f"{api_url}/health/ready")
    value = _json(payload, label="API readiness")
    if status != 200 or value.get("status") != "ready":
        raise AcceptanceError(f"API readiness failed: {value}")
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise AcceptanceError("API readiness returned no dependency checks")
    unhealthy = [
        str(item.get("name"))
        for item in dependencies
        if not isinstance(item, dict) or item.get("status") != "ok"
    ]
    if unhealthy:
        raise AcceptanceError(
            "API readiness has unhealthy dependencies: " + ", ".join(unhealthy)
        )
    return value


def _validate_session(
    value: dict[str, Any],
    *,
    shop_domain: str,
) -> dict[str, object]:
    if value.get("shop_domain") != shop_domain:
        raise AcceptanceError(
            "Authenticated Shopify session does not match the expected store"
        )
    invitation_status = value.get("invitation_status")
    if invitation_status not in {"pending", "activated"}:
        raise AcceptanceError(
            f"Unexpected invitation status: {invitation_status!r}"
        )
    if value.get("feature_tier") not in {"demo", "plus_demo"}:
        raise AcceptanceError("Shopify session returned an invalid feature tier")
    forbidden = _contains_forbidden_key(value)
    if forbidden:
        raise AcceptanceError(f"Shopify session exposed forbidden field {forbidden}")
    return {
        "shop_domain": shop_domain,
        "invitation_status": invitation_status,
        "feature_tier": value["feature_tier"],
        "activated_workspace_id": value.get("activated_workspace_id"),
        "session_expires_at": value.get("session_expires_at"),
    }


def _validate_installation(
    value: dict[str, Any],
    *,
    shop_domain: str,
) -> dict[str, object]:
    if value.get("shop_domain") != shop_domain:
        raise AcceptanceError("Installation status belongs to a different Shopify store")
    if value.get("installation_status") not in {
        "active",
        "refresh_required",
        "disconnected",
        "failed",
    }:
        raise AcceptanceError("Installation returned an invalid status")
    if value.get("sync_status") not in {
        "not_started",
        "queued",
        "coalesced",
        "running",
        "completed",
        "failed",
    }:
        raise AcceptanceError("Installation returned an invalid sync status")
    forbidden = _contains_forbidden_key(value)
    if forbidden:
        raise AcceptanceError(f"Installation exposed forbidden field {forbidden}")
    return {
        "shop_domain": shop_domain,
        "workspace_id": value.get("workspace_id"),
        "installation_status": value.get("installation_status"),
        "sync_status": value.get("sync_status"),
        "product_count": _nonnegative_int(value, "product_count"),
        "variant_count": _nonnegative_int(value, "variant_count"),
        "warning_count": _nonnegative_int(value, "warning_count"),
        "assigned_category_count": _nonnegative_int(
            value,
            "assigned_category_count",
        ),
        "ambiguous_category_count": _nonnegative_int(
            value,
            "ambiguous_category_count",
        ),
        "unclassified_category_count": _nonnegative_int(
            value,
            "unclassified_category_count",
        ),
        "last_successful_sync_at": value.get("last_successful_sync_at"),
        "reauthorization_required": value.get("reauthorization_required") is True,
    }


def _secret(
    env_name: str,
    *,
    prompt: str,
    read_stdin: bool,
) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    if read_stdin:
        return getpass.getpass(prompt).strip()
    return ""


def _write_report(path_value: str | None, report: dict[str, object]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run non-destructive and explicitly enabled acceptance checks for "
            "Catora's public-distribution Shopify app."
        )
    )
    parser.add_argument(
        "--app-url",
        default=os.getenv(
            "CATORA_SHOPIFY_ACCEPT_APP_URL",
            "https://shopify.catora.codistan.org",
        ),
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv(
            "CATORA_SHOPIFY_ACCEPT_API_URL",
            "https://api.catora.codistan.org",
        ),
    )
    parser.add_argument(
        "--shop-domain",
        default=os.getenv("CATORA_SHOPIFY_ACCEPT_SHOP_DOMAIN", ""),
    )
    parser.add_argument(
        "--expected-api-key",
        default=os.getenv("CATORA_SHOPIFY_ACCEPT_API_KEY", ""),
    )
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--product-webhook", action="store_true")
    parser.add_argument("--session-token-stdin", action="store_true")
    parser.add_argument("--public-secret-stdin", action="store_true")
    parser.add_argument(
        "--report",
        default=os.getenv("CATORA_SHOPIFY_ACCEPT_REPORT_PATH", ""),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        app_url = _origin(args.app_url, label="App URL")
        api_url = _origin(args.api_url, label="API URL")
        shop_domain = _shop_domain(args.shop_domain) if args.shop_domain else ""
        expected_api_key = args.expected_api_key.strip() or None
        session_token = _secret(
            "CATORA_SHOPIFY_ACCEPT_SESSION_TOKEN",
            prompt="Fresh Shopify App Bridge ID token: ",
            read_stdin=args.session_token_stdin,
        )
        public_secret = _secret(
            "CATORA_SHOPIFY_ACCEPT_PUBLIC_SECRET",
            prompt="Shopify public app client secret: ",
            read_stdin=args.public_secret_stdin,
        )
        if (args.activate or args.sync or session_token) and not shop_domain:
            raise AcceptanceError(
                "--shop-domain is required for authenticated acceptance checks"
            )
        if args.activate and not session_token:
            raise AcceptanceError("Activation requires a fresh Shopify session token")
        if args.sync and not session_token:
            raise AcceptanceError("Synchronization requires a fresh Shopify session token")
        if args.product_webhook and (not public_secret or not shop_domain):
            raise AcceptanceError(
                "Product webhook acceptance requires the public secret and shop domain"
            )

        report: dict[str, object] = {
            "app_url": app_url,
            "api_url": api_url,
            "shop_domain": shop_domain or None,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checks": {},
            "destructive_checks_executed": False,
        }
        checks = report["checks"]
        assert isinstance(checks, dict)

        checks["app_home"] = _validate_app_home(
            app_url,
            expected_api_key=expected_api_key,
        )
        checks["api_readiness"] = _validate_readiness(api_url)

        session: dict[str, Any] | None = None
        if session_token:
            session = _bearer_request(
                app_url,
                "/api/v1/shopify/public/session",
                session_token,
            )
            checks["session"] = _validate_session(
                session,
                shop_domain=shop_domain,
            )

        if args.activate:
            if session is None:
                raise AcceptanceError("Activation could not resolve the Shopify session")
            if session.get("invitation_status") == "pending":
                activation = _bearer_request(
                    app_url,
                    "/api/v1/shopify/public/activate",
                    session_token,
                    method="POST",
                )
                forbidden = _contains_forbidden_key(activation)
                if forbidden:
                    raise AcceptanceError(
                        f"Activation exposed forbidden field {forbidden}"
                    )
                if activation.get("shop_domain") != shop_domain:
                    raise AcceptanceError("Activation returned a different Shopify store")
                checks["activation"] = {
                    "created": activation.get("created") is True,
                    "installation_status": activation.get("installation_status"),
                    "sync_status": activation.get("sync_status"),
                    "workspace_id": activation.get("workspace_id"),
                }
            else:
                checks["activation"] = {"already_activated": True}

        if session_token and (
            args.activate or session and session.get("invitation_status") == "activated"
        ):
            installation = _bearer_request(
                app_url,
                "/api/v1/shopify/public/installation",
                session_token,
            )
            checks["installation"] = _validate_installation(
                installation,
                shop_domain=shop_domain,
            )

        if args.sync:
            synchronized = _bearer_request(
                app_url,
                "/api/v1/shopify/public/installation/sync",
                session_token,
                method="POST",
            )
            checks["manual_sync"] = _validate_installation(
                synchronized,
                shop_domain=shop_domain,
            )

        if public_secret:
            checks["customer_data_request"] = _signed_webhook(
                api_url,
                "/api/v1/shopify/compliance",
                topic="customers/data_request",
                shop_domain=shop_domain or "acceptance-probe.myshopify.com",
                secret=public_secret,
                body={
                    "shop_id": 1,
                    "shop_domain": shop_domain
                    or "acceptance-probe.myshopify.com",
                    "customer": {"id": 1},
                    "orders_requested": [],
                },
            )

        if args.product_webhook:
            checks["product_webhook"] = _signed_webhook(
                api_url,
                "/api/v1/shopify/webhooks",
                topic="products/update",
                shop_domain=shop_domain,
                secret=public_secret,
                body={"id": 1, "title": "Catora acceptance probe"},
            )

        report["completed_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        )
        report["ok"] = True
        _write_report(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (AcceptanceError, ValueError) as exc:
        print(f"Shopify public app acceptance failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
