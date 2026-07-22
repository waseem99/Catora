from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from catora_api.normalization.types import (
    NormalizationBatch,
    NormalizedAttribute,
    NormalizedProduct,
    NormalizedVariant,
)
from catora_api.normalization.values import (
    normalize_batch_values,
    normalize_boolean,
    normalize_choice,
    normalize_currency,
    normalize_date,
    normalize_decimal,
    normalize_dimensions,
    normalize_measurement,
    normalize_typed_value,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("210 cm", "2100"),
        ("2.1 m", "2100"),
        ("2100 mm", "2100"),
        ("10 in", "254"),
    ],
)
def test_equivalent_lengths_share_canonical_millimeters(
    raw: str,
    expected: str,
) -> None:
    parsed = normalize_measurement(raw, expected_quantity="length")

    assert parsed is not None
    assert parsed.unit == "mm"
    assert isinstance(parsed.value, dict)
    assert parsed.value["canonical_value"] == expected
    assert parsed.value["raw"] == raw


def test_mass_is_standardized_to_grams_while_retaining_source_unit() -> None:
    parsed = normalize_measurement("2 lb", expected_quantity="mass")

    assert parsed is not None
    assert parsed.unit == "g"
    assert isinstance(parsed.value, dict)
    assert parsed.value["canonical_value"] == "907.18474"
    assert parsed.value["source_unit"] == "lb"


def test_structured_source_measurement_is_supported() -> None:
    parsed = normalize_measurement(
        '{"value": 2.1, "unit": "METERS"}',
        expected_quantity="length",
    )

    assert parsed is not None
    assert isinstance(parsed.value, dict)
    assert parsed.value["canonical_value"] == "2100"
    assert parsed.value["source_unit"] == "m"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("210 x 90 x 75 cm", ("2100", "900", "750")),
        ("2.1m × 90cm × 750mm", ("2100", "900", "750")),
    ],
)
def test_dimensions_accept_shared_or_per_axis_units(
    raw: str,
    expected: tuple[str, str, str],
) -> None:
    parsed = normalize_dimensions(raw)

    assert parsed is not None
    assert parsed.unit == "mm"
    assert isinstance(parsed.value, dict)
    assert (
        parsed.value["axis_1"],
        parsed.value["axis_2"],
        parsed.value["axis_3"],
    ) == expected


@pytest.mark.parametrize("raw", ["yes", "TRUE", "1", True])
def test_boolean_true_values(raw: object) -> None:
    parsed = normalize_boolean(raw)
    assert parsed is not None
    assert parsed.value is True


@pytest.mark.parametrize("raw", ["no", "FALSE", "0", False])
def test_boolean_false_values(raw: object) -> None:
    parsed = normalize_boolean(raw)
    assert parsed is not None
    assert parsed.value is False


def test_decimal_currency_and_date_are_conservative() -> None:
    decimal_value = normalize_decimal("1299.00")
    currency_value = normalize_currency("usd")
    iso_date = normalize_date("2026-07-21")
    date_value = normalize_date(date(2026, 7, 21))
    datetime_value = normalize_date(datetime(2026, 7, 21, 10, 30))

    assert decimal_value is not None and decimal_value.value == "1299"
    assert normalize_decimal("1,299.00") is None
    assert currency_value is not None and currency_value.value == "USD"
    assert normalize_currency("US$") is None
    assert iso_date is not None and iso_date.value == "2026-07-21"
    assert normalize_date("07/21/2026") is None
    assert date_value is not None and date_value.value == "2026-07-21"
    assert datetime_value is not None and datetime_value.value == "2026-07-21"


def test_choice_aliases_preserve_raw_and_flag_unmapped_values() -> None:
    aliases = {"grey": "gray", "charcoal grey": "charcoal"}

    mapped = normalize_choice(" Grey ", aliases=aliases, value_type="color")
    unmapped = normalize_choice("Ocean Blue", aliases=aliases, value_type="color")

    assert mapped is not None
    assert mapped.value == {"raw": "Grey", "canonical": "gray"}
    assert mapped.warning is None
    assert unmapped is not None
    assert unmapped.value == {"raw": "Ocean Blue", "canonical": "Ocean Blue"}
    assert unmapped.confidence == "medium"
    assert unmapped.warning == "unmapped_color"


def test_typed_dispatch_rejects_quantity_mismatch_and_unknown_hints() -> None:
    assert normalize_typed_value("2 kg", hint="length") is None
    assert normalize_typed_value("2 kg", hint="weight") is not None
    assert normalize_typed_value("value", hint="unknown") is None


def test_batch_pass_normalizes_product_and_variant_attributes() -> None:
    record_id = uuid.uuid4()
    product = NormalizedProduct(
        canonical_key="source:test:product:1",
        source_id="1",
        title="Cloud Sofa",
        source_record_id=record_id,
        title_field_path="product.title",
        attributes=(
            NormalizedAttribute(
                key="metafield.specs.weight",
                value='{"value": 2, "unit": "KILOGRAMS"}',
                value_type="weight",
                source_record_id=record_id,
                field_path="product.metafields.weight",
            ),
            NormalizedAttribute(
                key="metafield.specs.color",
                value="Grey",
                value_type="string",
                source_record_id=record_id,
                field_path="product.metafields.color",
            ),
            NormalizedAttribute(
                key="metafield.specs.material",
                value="Unknown Blend",
                value_type="string",
                source_record_id=record_id,
                field_path="product.metafields.material",
            ),
        ),
        variants=(
            NormalizedVariant(
                canonical_key="source:test:variant:1",
                source_id="1",
                source_record_id=record_id,
                attributes=(
                    NormalizedAttribute(
                        key="price",
                        value="1299.00",
                        value_type="decimal",
                        source_record_id=record_id,
                        field_path="variant.price",
                    ),
                    NormalizedAttribute(
                        key="available_for_sale",
                        value="yes",
                        value_type="boolean",
                        source_record_id=record_id,
                        field_path="variant.availableForSale",
                    ),
                ),
            ),
        ),
    )

    normalized = normalize_batch_values(
        NormalizationBatch(products=(product,)),
        source_config={
            "normalization_aliases": {
                "color": {"grey": "gray"},
                "material": {"solid wood": "wood"},
            }
        },
    ).products[0]

    weight, color, material = normalized.attributes
    price, availability = normalized.variants[0].attributes
    assert weight.value_type == "measurement"
    assert weight.unit == "g"
    assert isinstance(weight.value, dict)
    assert weight.value["canonical_value"] == "2000"
    assert color.value == {"raw": "Grey", "canonical": "gray"}
    assert color.confidence == "high"
    assert material.confidence == "medium"
    assert "unmapped_material:metafield.specs.material" in normalized.warnings
    assert price.value == "1299"
    assert availability.value is True
