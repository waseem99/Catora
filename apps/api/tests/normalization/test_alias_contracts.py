from __future__ import annotations

import pytest
from pydantic import ValidationError

from catora_api.schemas.ingestion import (
    PublicCatalogSourceCreateRequest,
    ShopifySourceCreateRequest,
)


def test_shopify_alias_contract_normalizes_keys_and_values() -> None:
    request = ShopifySourceCreateRequest(
        name="Shopify",
        shop_domain="demo.myshopify.com",
        credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
        normalization_aliases={
            "color": {"  Charcoal   Grey ": " Charcoal "},
            "material": {"Solid   Wood": "Wood"},
        },
    )

    assert request.normalization_aliases.color == {
        "charcoal grey": "Charcoal"
    }
    assert request.normalization_aliases.material == {
        "solid wood": "Wood"
    }


def test_public_alias_contract_is_bounded_and_forbids_extra_groups() -> None:
    request = PublicCatalogSourceCreateRequest(
        name="Public",
        source_type="urls",
        product_urls=["https://shop.example.com/products/one"],
        authorized_domain_confirmed=True,
        normalization_aliases={"color": {"grey": "gray"}},
    )
    assert request.normalization_aliases.color == {"grey": "gray"}

    with pytest.raises(ValidationError):
        PublicCatalogSourceCreateRequest(
            name="Public",
            source_type="urls",
            product_urls=["https://shop.example.com/products/one"],
            authorized_domain_confirmed=True,
            normalization_aliases={"brand": {"acme": "ACME"}},
        )


def test_alias_contract_rejects_blank_or_oversized_values() -> None:
    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest(
            name="Shopify",
            shop_domain="demo.myshopify.com",
            credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
            normalization_aliases={"color": {"grey": "   "}},
        )

    with pytest.raises(ValidationError):
        ShopifySourceCreateRequest(
            name="Shopify",
            shop_domain="demo.myshopify.com",
            credential_ref="env:CATORA_CONNECTOR_SECRET_DEMO",
            normalization_aliases={"material": {"x" * 101: "wood"}},
        )
