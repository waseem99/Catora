from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest


def _load_acceptance_module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts/accept_shopify_public_app.py"
    spec = importlib.util.spec_from_file_location(
        "catora_shopify_public_acceptance",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Shopify public acceptance harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acceptance = _load_acceptance_module()
AcceptanceError = cast(type[Exception], acceptance.AcceptanceError)
_origin = cast(Any, acceptance._origin)
_shop_domain = cast(Any, acceptance._shop_domain)
_contains_forbidden_key = cast(Any, acceptance._contains_forbidden_key)
_validate_session = cast(Any, acceptance._validate_session)
_validate_installation = cast(Any, acceptance._validate_installation)


def test_acceptance_origins_and_shop_domain_are_strict() -> None:
    assert _origin("https://shopify.catora.codistan.org/", label="App URL") == (
        "https://shopify.catora.codistan.org"
    )
    assert _shop_domain("Prospect-Store.myshopify.com") == (
        "prospect-store.myshopify.com"
    )
    with pytest.raises(AcceptanceError, match="HTTPS origin"):
        _origin("http://shopify.catora.codistan.org", label="App URL")
    with pytest.raises(AcceptanceError, match="myshopify"):
        _shop_domain("prospect.example.com")


def test_acceptance_rejects_nested_credential_fields() -> None:
    assert _contains_forbidden_key({"status": "active"}) is None
    assert _contains_forbidden_key(
        {"installation": {"encrypted_refresh_token": "redacted"}}
    ) == "encrypted_refresh_token"


def test_acceptance_validates_bounded_session() -> None:
    result = _validate_session(
        {
            "shop_domain": "prospect-store.myshopify.com",
            "invitation_status": "activated",
            "feature_tier": "demo",
            "activated_workspace_id": "workspace-id",
            "session_expires_at": "2026-07-24T12:01:00Z",
        },
        shop_domain="prospect-store.myshopify.com",
    )
    assert result["invitation_status"] == "activated"
    with pytest.raises(AcceptanceError, match="forbidden"):
        _validate_session(
            {
                "shop_domain": "prospect-store.myshopify.com",
                "invitation_status": "activated",
                "feature_tier": "demo",
                "access_token": "not-allowed",
            },
            shop_domain="prospect-store.myshopify.com",
        )


def test_acceptance_validates_installation_counts_and_status() -> None:
    result = _validate_installation(
        {
            "shop_domain": "prospect-store.myshopify.com",
            "workspace_id": "workspace-id",
            "installation_status": "active",
            "sync_status": "completed",
            "product_count": 100,
            "variant_count": 150,
            "warning_count": 2,
            "assigned_category_count": 80,
            "ambiguous_category_count": 10,
            "unclassified_category_count": 10,
            "last_successful_sync_at": "2026-07-24T12:00:00Z",
            "reauthorization_required": False,
        },
        shop_domain="prospect-store.myshopify.com",
    )
    assert result["product_count"] == 100
    assert result["sync_status"] == "completed"
    with pytest.raises(AcceptanceError, match="product_count"):
        _validate_installation(
            {
                "shop_domain": "prospect-store.myshopify.com",
                "installation_status": "active",
                "sync_status": "completed",
                "product_count": -1,
                "variant_count": 0,
                "warning_count": 0,
                "assigned_category_count": 0,
                "ambiguous_category_count": 0,
                "unclassified_category_count": 0,
            },
            shop_domain="prospect-store.myshopify.com",
        )
