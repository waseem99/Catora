from __future__ import annotations

import json
from importlib.resources import files

import pytest

from catora_api.taxonomy.loader import load_bundled_taxonomy
from catora_api.taxonomy.resolution import classify_product, resolve_categories


def test_category_inheritance_resolves_shared_and_overridden_requirements() -> None:
    package = load_bundled_taxonomy()
    categories = resolve_categories(package)

    sofa = categories["sofas_sectionals"]
    assert sofa.parent_chain == ("home_products", "furniture")
    assert sofa.requirements["usage_environment"] == "required"
    assert sofa.requirement_sources["usage_environment"] == "home_products"
    assert sofa.requirements["width_mm"] == "required"
    assert sofa.requirement_sources["width_mm"] == "furniture"
    assert sofa.requirements["seating_capacity"] == "required"
    assert sofa.requirement_sources["seating_capacity"] == "sofas_sectionals"

    rug = categories["rugs_soft_furnishings"]
    assert rug.requirements["height_mm"] == "not_applicable"
    assert rug.requirement_sources["height_mm"] == "rugs_soft_furnishings"


def _mapping_fixtures() -> list[dict[str, str]]:
    resource = files("catora_api.taxonomy.data").joinpath(
        "furniture_category_fixtures.json"
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


@pytest.mark.parametrize("fixture", _mapping_fixtures())
def test_representative_furniture_fixture_maps(fixture: dict[str, str]) -> None:
    result = classify_product(load_bundled_taxonomy(), title=fixture["title"])

    assert result.status == "assigned"
    assert result.primary_category_key == fixture["expected"]


def test_ambiguous_category_is_flagged_instead_of_forced() -> None:
    result = classify_product(
        load_bundled_taxonomy(),
        title="Chair desk combo",
    )

    assert result.status == "ambiguous"
    assert result.primary_category_key is None
    assert result.candidate_keys == (
        "chairs_recliners",
        "desks_office_furniture",
    )


def test_secondary_category_signal_is_retained_without_replacing_primary() -> None:
    result = classify_product(
        load_bundled_taxonomy(),
        title="Outdoor dining chair",
    )

    assert result.status == "assigned"
    assert result.primary_category_key == "dining_tables_chairs"
    assert result.secondary_tag_keys == ("chairs_recliners",)


def test_unclassified_product_is_not_forced() -> None:
    result = classify_product(load_bundled_taxonomy(), title="Unknown home object")

    assert result.status == "unclassified"
    assert result.primary_category_key is None
    assert result.candidate_keys == ()
