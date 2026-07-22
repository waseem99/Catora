from __future__ import annotations

import pytest
from pydantic import ValidationError

from catora_api.schemas.intents import BuyerIntentParseRequest


def test_parse_request_normalizes_query_and_allowlists() -> None:
    payload = BuyerIntentParseRequest(
        query="  compact   sofa  ",
        allowed_category_keys=(" Sofas ",),
        allowed_field_keys=("width",),
        locale="en-GB",
    )

    assert payload.query == "compact sofa"
    assert payload.allowed_category_keys == ("sofas",)
    assert payload.allowed_field_keys == ("width",)

    with pytest.raises(ValidationError):
        BuyerIntentParseRequest(
            query="compact sofa",
            allowed_field_keys=("Width Invalid",),
        )


def test_parse_preview_openapi_contract_is_registered() -> None:
    from catora_api.main import app

    path = "/api/v1/workspaces/{workspace_id}/buyer-intents/parse-preview"
    operation = app.openapi()["paths"][path]["post"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/BuyerIntentParsePreview")
