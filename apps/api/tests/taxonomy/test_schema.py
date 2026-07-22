from __future__ import annotations

import json
from importlib.resources import files

import pytest
from pydantic import ValidationError

from catora_api.taxonomy.loader import load_bundled_taxonomy
from catora_api.taxonomy.schema import TaxonomyPackage

EXPECTED_ASSIGNABLE_CATEGORIES = {
    "sofas_sectionals",
    "chairs_recliners",
    "beds_mattresses",
    "dining_tables_chairs",
    "desks_office_furniture",
    "storage_cabinets",
    "outdoor_furniture",
    "lighting",
    "rugs_soft_furnishings",
    "home_accessories",
}


def test_bundled_taxonomy_is_valid_and_complete() -> None:
    package = load_bundled_taxonomy()

    assert package.version == "1.0.0"
    assert package.immutable is True
    assert len(package.fields) >= 20
    assert {
        category.key for category in package.categories if category.assignable_primary
    } == EXPECTED_ASSIGNABLE_CATEGORIES


def test_checked_in_json_schema_matches_runtime_contract() -> None:
    resource = files("catora_api.taxonomy.data").joinpath("taxonomy-package.schema.json")
    checked_in = json.loads(resource.read_text(encoding="utf-8"))

    assert checked_in == TaxonomyPackage.model_json_schema()


def test_unknown_taxonomy_fields_fail_with_clear_validation() -> None:
    payload = load_bundled_taxonomy().model_dump(mode="json")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TaxonomyPackage.model_validate(payload)


def test_unknown_category_field_reference_is_rejected() -> None:
    payload = load_bundled_taxonomy().model_dump(mode="json")
    categories = payload["categories"]
    assert isinstance(categories, list)
    first = categories[0]
    assert isinstance(first, dict)
    requirements = first["requirements"]
    assert isinstance(requirements, dict)
    requirements["does_not_exist"] = "required"

    with pytest.raises(ValidationError, match="references unknown fields"):
        TaxonomyPackage.model_validate(payload)


def test_category_inheritance_cycle_is_rejected() -> None:
    payload = load_bundled_taxonomy().model_dump(mode="json")
    categories = payload["categories"]
    assert isinstance(categories, list)
    first = categories[0]
    second = categories[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    first["parent_key"] = second["key"]

    with pytest.raises(ValidationError, match="inheritance cycle"):
        TaxonomyPackage.model_validate(payload)
