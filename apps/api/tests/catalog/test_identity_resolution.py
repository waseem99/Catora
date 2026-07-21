from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catora_api.api.catalog_identity import router as catalog_identity_router
from catora_api.auth.roles import Role, can
from catora_api.db.models.catalog import Product
from catora_api.identity_resolution.service import (
    CatalogIdentityService,
    _identifier,
    _pair,
    _ProductProfile,
)
from catora_api.main import app


def _product(title: str) -> Product:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    product_id = uuid.uuid4()
    return Product(
        id=product_id,
        workspace_id=uuid.uuid4(),
        canonical_key=f"source:test:product:{product_id}",
        title=title,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _profile(
    title: str,
    *,
    brands: set[str] | None = None,
    gtins: set[str] | None = None,
    mpns: set[str] | None = None,
    skus: set[str] | None = None,
) -> _ProductProfile:
    product = _product(title)
    title_key = title.casefold()
    return _ProductProfile(
        product=product,
        title_key=title_key,
        title_tokens=tuple(title_key.split()),
        brands=frozenset(brands or set()),
        gtins=frozenset(gtins or set()),
        mpns=frozenset(mpns or set()),
        skus=frozenset(skus or set()),
    )


def test_exact_gtin_is_a_deterministic_review_candidate() -> None:
    left = _profile("Cloud Sofa", gtins={"0123456789012"})
    right = _profile("Sofa Cloud", gtins={"0123456789012"})

    proposals = CatalogIdentityService()._proposals([left, right])
    proposal = proposals[_pair(left.product.id, right.product.id)]

    assert proposal.match_type == "deterministic"
    assert proposal.score_basis_points == 10000
    assert proposal.signals[0]["kind"] == "gtin_exact"


def test_exact_mpn_requires_same_brand_for_deterministic_match() -> None:
    left = _profile("Cloud Sofa", brands={"acme"}, mpns={"sofa100"})
    same_brand = _profile("Cloud Sofa 3 Seat", brands={"acme"}, mpns={"sofa100"})
    other_brand = _profile("Cloud Sofa", brands={"other"}, mpns={"sofa100"})

    proposals = CatalogIdentityService()._proposals([left, same_brand, other_brand])

    assert _pair(left.product.id, same_brand.product.id) in proposals
    assert proposals[_pair(left.product.id, same_brand.product.id)].match_type == "deterministic"
    assert _pair(left.product.id, other_brand.product.id) not in proposals


def test_sku_is_never_treated_as_globally_unique() -> None:
    left = _profile("Cloud Sofa", skus={"sofa100"})
    right = _profile("Dining Table", skus={"sofa100"})

    proposals = CatalogIdentityService()._proposals([left, right])

    assert _pair(left.product.id, right.product.id) not in proposals


def test_title_brand_similarity_produces_fuzzy_review_only() -> None:
    left = _profile("Cloud Sofa Three Seat", brands={"acme"})
    right = _profile("Cloud Sofa 3 Seat", brands={"acme"})

    proposals = CatalogIdentityService()._proposals([left, right])
    proposal = proposals[_pair(left.product.id, right.product.id)]

    assert proposal.match_type == "fuzzy"
    assert proposal.score_basis_points < 10000
    assert {signal["kind"] for signal in proposal.signals} == {
        "title_similarity",
        "brand_exact",
    }


def test_identifier_normalization_is_unicode_and_format_stable() -> None:
    assert _identifier(" ACME–SOFA 100 ") == "acmesofa100"
    assert _identifier("ＡＣＭＥ-100") == "acme100"


def test_identity_management_is_admin_only() -> None:
    assert can(Role.OWNER, "catalog.identity.manage")
    assert can(Role.ADMIN, "catalog.identity.manage")
    assert not can(Role.ANALYST, "catalog.identity.manage")
    assert not can(Role.REVIEWER, "catalog.identity.manage")
    assert not can(Role.VIEWER, "catalog.identity.manage")


def test_identity_routes_are_mounted_with_expected_methods() -> None:
    expected = {
        "/api/v1/workspaces/{workspace_id}/identity-candidates": {"get"},
        "/api/v1/workspaces/{workspace_id}/identity-candidates/refresh": {"post"},
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/identity": {"get"},
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/identity-link": {"post"},
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/identity-unlink": {"post"},
        "/api/v1/workspaces/{workspace_id}/identity-candidates/{candidate_id}/reject": {"post"},
    }
    router_paths = {route.path for route in catalog_identity_router.routes}
    openapi_paths = app.openapi()["paths"]

    assert set(expected) <= router_paths
    for path, methods in expected.items():
        assert path in openapi_paths
        assert set(openapi_paths[path]) == methods
