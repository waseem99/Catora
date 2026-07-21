from __future__ import annotations

from datetime import date, datetime

import pytest

from catora_api.normalization.values import (
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
    assert normalize_decimal("1299.00").value == "1299"  # type: ignore[union-attr]
    assert normalize_decimal("1,299.00") is None
    assert normalize_currency("usd").value == "USD"  # type: ignore[union-attr]
    assert normalize_currency("US$") is None
    assert normalize_date("2026-07-21").value == "2026-07-21"  # type: ignore[union-attr]
    assert normalize_date("07/21/2026") is None
    assert normalize_date(date(2026, 7, 21)).value == "2026-07-21"  # type: ignore[union-attr]
    assert normalize_date(datetime(2026, 7, 21, 10, 30)).value == "2026-07-21"  # type: ignore[union-attr]


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
