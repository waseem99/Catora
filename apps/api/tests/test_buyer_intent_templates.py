from __future__ import annotations

import pytest

from catora_api.intents.templates import (
    BUILTIN_BUYER_INTENT_TEMPLATES,
    BuyerIntentTemplateNotFoundError,
    get_buyer_intent_template,
    list_buyer_intent_templates,
)
from catora_api.intents.types import StructuredBuyerIntent
from catora_api.taxonomy.loader import load_bundled_taxonomy


def test_templates_are_stable_unique_and_taxonomy_valid() -> None:
    taxonomy = load_bundled_taxonomy()
    known_categories = {
        category.key for category in taxonomy.categories if category.assignable_primary
    }
    known_fields = {field.key for field in taxonomy.fields}

    keys = [item.key for item in BUILTIN_BUYER_INTENT_TEMPLATES]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert len(keys) == 7

    for template in BUILTIN_BUYER_INTENT_TEMPLATES:
        assert template.taxonomy_version == taxonomy.version == "1.0.0"
        assert StructuredBuyerIntent.model_validate(
            template.structured_intent.model_dump(mode="json")
        ) == template.structured_intent
        assert set(template.structured_intent.category_keys) <= known_categories
        constraints = template.structured_intent.hard_constraints + tuple(
            item.constraint for item in template.structured_intent.soft_preferences
        )
        assert {item.field_key for item in constraints} <= known_fields


def test_template_filters_and_pagination_reconcile() -> None:
    compact = list_buyer_intent_templates(use_case=" Compact_Spaces ", offset=0, limit=100)
    assert compact.total == 2
    assert [item.key for item in compact.items] == [
        "compact_space_sofa",
        "low_assembly_storage",
    ]

    sofas = list_buyer_intent_templates(
        category_key=" SOFAS_SECTIONALS ",
        offset=1,
        limit=1,
    )
    assert sofas.total == 2
    assert [item.key for item in sofas.items] == ["family_friendly_sofa"]


def test_template_detail_is_normalized_and_not_found_is_non_disclosing() -> None:
    assert get_buyer_intent_template(" Compact_Space_Sofa ").key == "compact_space_sofa"
    with pytest.raises(BuyerIntentTemplateNotFoundError, match="not found"):
        get_buyer_intent_template("missing_template")


def test_template_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    collection_path = "/api/v1/workspaces/{workspace_id}/buyer-intent-templates"
    detail_path = (
        "/api/v1/workspaces/{workspace_id}/buyer-intent-templates/{template_key}"
    )
    collection = app.openapi()["paths"][collection_path]["get"]
    detail = app.openapi()["paths"][detail_path]["get"]

    assert collection["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/BuyerIntentTemplateListResponse")
    assert detail["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/BuyerIntentTemplateView")
