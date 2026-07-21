from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catora_api.api.catalog import _escape_like, _is_warning, _product_detail
from catora_api.db.models.catalog import (
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
)
from catora_api.main import app


def _now() -> datetime:
    return datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def test_catalog_routes_are_mounted_as_read_only_gets() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/v1/workspaces/{workspace_id}/products", "GET") in routes
    assert (
        "/api/v1/workspaces/{workspace_id}/products/{product_id}",
        "GET",
    ) in routes
    assert (
        "/api/v1/workspaces/{workspace_id}/products/{product_id}/provenance",
        "GET",
    ) in routes


def test_like_search_escapes_wildcards_and_backslashes() -> None:
    assert _escape_like(r"50%_off\sale") == r"50\%\_off\\sale"


def test_product_detail_groups_current_values_and_preserves_states() -> None:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    variant_id = uuid.uuid4()
    now = _now()
    product = Product(
        id=product_id,
        workspace_id=workspace_id,
        canonical_key="source:test:product:1",
        title="Cloud Sofa",
        status="active",
        created_at=now,
        updated_at=now,
    )
    variant = ProductVariant(
        id=variant_id,
        workspace_id=workspace_id,
        product_id=product_id,
        canonical_key="source:test:variant:1",
        sku="SOFA-BLUE",
        title="Blue",
        option_values={"Color": "Blue"},
        created_at=now,
        updated_at=now,
    )
    product_attribute = ProductAttribute(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        variant_id=None,
        key="description",
        value=None,
        value_type="string",
        value_state="missing",
        confidence="high",
        created_at=now,
        updated_at=now,
    )
    variant_attribute = ProductAttribute(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        variant_id=variant_id,
        key="color",
        value={"raw": "Grey", "canonical": "gray"},
        value_type="color",
        value_state="present",
        confidence="medium",
        created_at=now,
        updated_at=now,
    )
    product_image = ProductImage(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        variant_id=None,
        url="https://example.com/product.jpg",
        position=0,
        created_at=now,
        updated_at=now,
    )
    variant_image = ProductImage(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=product_id,
        variant_id=variant_id,
        url="https://example.com/blue.jpg",
        position=0,
        created_at=now,
        updated_at=now,
    )

    detail = _product_detail(
        product,
        variants=[variant],
        attributes=[product_attribute, variant_attribute],
        images=[product_image, variant_image],
        provenance_count=4,
    )

    assert detail.workspace_id == workspace_id
    assert [attribute.key for attribute in detail.product_attributes] == [
        "description"
    ]
    assert detail.product_attributes[0].value_state == "missing"
    assert len(detail.product_images) == 1
    assert len(detail.variants) == 1
    assert detail.variants[0].attributes[0].key == "color"
    assert detail.variants[0].images[0].url.endswith("blue.jpg")
    assert detail.warning_count == 2
    assert detail.provenance_count == 4


def test_warning_signal_covers_confidence_and_value_state() -> None:
    base = {
        "workspace_id": uuid.uuid4(),
        "product_id": uuid.uuid4(),
        "variant_id": None,
        "key": "material",
        "value": "wood",
        "value_type": "string",
        "created_at": _now(),
        "updated_at": _now(),
    }
    assert not _is_warning(
        ProductAttribute(
            **base,
            id=uuid.uuid4(),
            value_state="present",
            confidence="high",
        )
    )
    assert _is_warning(
        ProductAttribute(
            **base,
            id=uuid.uuid4(),
            value_state="conflicting",
            confidence="high",
        )
    )
    assert _is_warning(
        ProductAttribute(
            **base,
            id=uuid.uuid4(),
            value_state="present",
            confidence="low",
        )
    )
