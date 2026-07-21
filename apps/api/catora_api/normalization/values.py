from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from catora_api.normalization.types import (
    Confidence,
    JsonValue,
    NormalizationBatch,
    NormalizedAttribute,
    NormalizedProduct,
    NormalizedVariant,
)

Quantity = Literal["length", "mass"]
type ScalarValue = str | int | float | bool | None
type NormalizedValue = ScalarValue | list[ScalarValue] | dict[str, ScalarValue]

_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_MEASUREMENT_PATTERN = re.compile(
    r"^\s*(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit>mm|cm|m|in|inch|inches|ft|foot|feet|g|kg|lb|lbs|pound|pounds|oz)\s*$",
    re.IGNORECASE,
)
_DIMENSION_SPLIT_PATTERN = re.compile(r"\s*[x×]\s*", re.IGNORECASE)

_LENGTH_TO_MM: dict[str, Decimal] = {
    "mm": Decimal("1"),
    "cm": Decimal("10"),
    "m": Decimal("1000"),
    "in": Decimal("25.4"),
    "inch": Decimal("25.4"),
    "inches": Decimal("25.4"),
    "ft": Decimal("304.8"),
    "foot": Decimal("304.8"),
    "feet": Decimal("304.8"),
}
_MASS_TO_G: dict[str, Decimal] = {
    "g": Decimal("1"),
    "kg": Decimal("1000"),
    "lb": Decimal("453.59237"),
    "lbs": Decimal("453.59237"),
    "pound": Decimal("453.59237"),
    "pounds": Decimal("453.59237"),
    "oz": Decimal("28.349523125"),
}
_UNIT_ALIASES = {
    "millimeter": "mm",
    "millimeters": "mm",
    "centimeter": "cm",
    "centimeters": "cm",
    "meter": "m",
    "meters": "m",
    "inch": "in",
    "inches": "in",
    "foot": "ft",
    "feet": "ft",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "pound": "lb",
    "pounds": "lb",
    "ounce": "oz",
    "ounces": "oz",
}
_TRUE_VALUES = frozenset({"true", "yes", "y", "1", "on"})
_FALSE_VALUES = frozenset({"false", "no", "n", "0", "off"})
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_CONFIDENCE_ORDER: dict[Confidence, int] = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


@dataclass(frozen=True, slots=True)
class ParsedValue:
    value: NormalizedValue
    value_type: str
    unit: str | None = None
    confidence: Confidence = "high"
    warning: str | None = None


def normalize_decimal(value: object) -> ParsedValue | None:
    if isinstance(value, bool):
        return None
    text = _clean_scalar_text(value)
    if text is None or not _NUMBER_PATTERN.fullmatch(text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return ParsedValue(value=_decimal_text(number), value_type="decimal")


def normalize_boolean(value: object) -> ParsedValue | None:
    if isinstance(value, bool):
        return ParsedValue(value=value, value_type="boolean")
    text = _clean_scalar_text(value)
    if text is None:
        return None
    folded = text.casefold()
    if folded in _TRUE_VALUES:
        return ParsedValue(value=True, value_type="boolean")
    if folded in _FALSE_VALUES:
        return ParsedValue(value=False, value_type="boolean")
    return None


def normalize_date(value: object) -> ParsedValue | None:
    if isinstance(value, datetime):
        return ParsedValue(value=value.date().isoformat(), value_type="date")
    if isinstance(value, date):
        return ParsedValue(value=value.isoformat(), value_type="date")
    text = _clean_scalar_text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return ParsedValue(value=parsed.isoformat(), value_type="date")


def normalize_currency(value: object) -> ParsedValue | None:
    text = _clean_scalar_text(value)
    if text is None:
        return None
    code = text.upper()
    if not _CURRENCY_PATTERN.fullmatch(code):
        return None
    return ParsedValue(value=code, value_type="currency")


def normalize_measurement(
    value: object,
    *,
    expected_quantity: Quantity | None = None,
) -> ParsedValue | None:
    text = _measurement_text(value)
    if text is None:
        return None
    match = _MEASUREMENT_PATTERN.fullmatch(text)
    if match is None:
        return None
    number = Decimal(match.group("value"))
    source_unit = match.group("unit").casefold()
    if source_unit in _LENGTH_TO_MM:
        quantity: Quantity = "length"
        canonical_unit = "mm"
        canonical_value = number * _LENGTH_TO_MM[source_unit]
    elif source_unit in _MASS_TO_G:
        quantity = "mass"
        canonical_unit = "g"
        canonical_value = number * _MASS_TO_G[source_unit]
    else:  # pragma: no cover - regex and maps are intentionally aligned
        return None
    if expected_quantity is not None and expected_quantity != quantity:
        return None
    return ParsedValue(
        value={
            "raw": text,
            "quantity": quantity,
            "canonical_value": _decimal_text(canonical_value),
            "canonical_unit": canonical_unit,
            "source_value": _decimal_text(number),
            "source_unit": source_unit,
        },
        value_type="measurement",
        unit=canonical_unit,
    )


def normalize_dimensions(value: object) -> ParsedValue | None:
    text = _clean_scalar_text(value)
    if text is None:
        return None
    parts = _DIMENSION_SPLIT_PATTERN.split(text)
    if len(parts) not in {2, 3}:
        return None

    trailing_match = _MEASUREMENT_PATTERN.fullmatch(parts[-1])
    if trailing_match is None:
        return None
    shared_unit = trailing_match.group("unit")
    canonical_values: list[str] = []
    for part in parts:
        normalized = normalize_measurement(part, expected_quantity="length")
        if normalized is None:
            normalized = normalize_measurement(
                f"{part} {shared_unit}",
                expected_quantity="length",
            )
        if normalized is None or not isinstance(normalized.value, dict):
            return None
        canonical_value = normalized.value.get("canonical_value")
        if not isinstance(canonical_value, str):
            return None
        canonical_values.append(canonical_value)

    normalized_dimensions: dict[str, ScalarValue] = {
        "raw": text,
        "quantity": "dimensions",
        "canonical_unit": "mm",
        "axis_1": canonical_values[0],
        "axis_2": canonical_values[1],
        "source_unit": shared_unit.casefold(),
    }
    if len(canonical_values) == 3:
        normalized_dimensions["axis_3"] = canonical_values[2]
    return ParsedValue(
        value=normalized_dimensions,
        value_type="dimensions",
        unit="mm",
    )


def normalize_choice(
    value: object,
    *,
    aliases: dict[str, str],
    value_type: str,
) -> ParsedValue | None:
    text = _clean_scalar_text(value)
    if text is None:
        return None
    normalized_key = _choice_key(text)
    canonical = aliases.get(normalized_key)
    if canonical is None:
        return ParsedValue(
            value={"raw": text, "canonical": text},
            value_type=value_type,
            confidence="medium",
            warning=f"unmapped_{value_type}",
        )
    return ParsedValue(
        value={"raw": text, "canonical": canonical},
        value_type=value_type,
    )


def normalize_typed_value(
    value: object,
    *,
    hint: str | None = None,
    aliases: dict[str, str] | None = None,
) -> ParsedValue | None:
    normalized_hint = (hint or "").casefold().replace("-", "_")
    if normalized_hint in {"boolean", "bool"}:
        return normalize_boolean(value)
    if normalized_hint in {"date", "iso_date"}:
        return normalize_date(value)
    if normalized_hint in {"currency", "currency_code"}:
        return normalize_currency(value)
    if normalized_hint in {"length", "distance", "dimension"}:
        return normalize_measurement(value, expected_quantity="length")
    if normalized_hint in {"mass", "weight"}:
        return normalize_measurement(value, expected_quantity="mass")
    if normalized_hint in {"dimensions", "size"}:
        return normalize_dimensions(value)
    if normalized_hint in {"decimal", "price", "number", "number_decimal"}:
        return normalize_decimal(value)
    if aliases is not None and normalized_hint:
        return normalize_choice(
            value,
            aliases=aliases,
            value_type=normalized_hint,
        )
    return None


def normalize_batch_values(
    batch: NormalizationBatch,
    *,
    source_config: Mapping[str, Any],
) -> NormalizationBatch:
    aliases = _alias_config(source_config)
    products = tuple(_normalize_product(product, aliases) for product in batch.products)
    return replace(batch, products=products)


def _normalize_product(
    product: NormalizedProduct,
    aliases: dict[str, dict[str, str]],
) -> NormalizedProduct:
    product_attributes, product_warnings = _normalize_attributes(
        product.attributes,
        aliases,
    )
    variants: list[NormalizedVariant] = []
    warnings = list(product.warnings)
    warnings.extend(product_warnings)
    for variant in product.variants:
        variant_attributes, variant_warnings = _normalize_attributes(
            variant.attributes,
            aliases,
        )
        variants.append(replace(variant, attributes=variant_attributes))
        warnings.extend(variant_warnings)
    return replace(
        product,
        attributes=product_attributes,
        variants=tuple(variants),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _normalize_attributes(
    attributes: tuple[NormalizedAttribute, ...],
    aliases: dict[str, dict[str, str]],
) -> tuple[tuple[NormalizedAttribute, ...], tuple[str, ...]]:
    normalized: list[NormalizedAttribute] = []
    warnings: list[str] = []
    for attribute in attributes:
        hint = _attribute_hint(attribute)
        if hint is None:
            normalized.append(attribute)
            continue
        choice_aliases = aliases.get(hint)
        if hint in {"color", "material"} and choice_aliases is None:
            choice_aliases = {}
        parsed = normalize_typed_value(
            attribute.value,
            hint=hint,
            aliases=choice_aliases,
        )
        if parsed is None:
            normalized.append(attribute)
            warnings.append(f"unparsed_{hint}:{attribute.key}")
            continue
        normalized.append(
            replace(
                attribute,
                value=cast(JsonValue, parsed.value),
                value_type=parsed.value_type,
                unit=parsed.unit,
                confidence=_lower_confidence(
                    attribute.confidence,
                    parsed.confidence,
                ),
            )
        )
        if parsed.warning:
            warnings.append(f"{parsed.warning}:{attribute.key}")
    return tuple(normalized), tuple(warnings)


def _attribute_hint(attribute: NormalizedAttribute) -> str | None:
    value_type = attribute.value_type.casefold().replace("-", "_")
    if value_type in {
        "boolean",
        "bool",
        "currency",
        "currency_code",
        "date",
        "iso_date",
        "dimension",
        "dimensions",
        "length",
        "distance",
        "mass",
        "weight",
        "decimal",
        "price",
        "number",
        "number_decimal",
    }:
        return value_type

    key = attribute.key.casefold().replace("-", "_")
    leaf = key.rsplit(".", 1)[-1]
    if leaf in {"price", "compare_at_price"}:
        return "decimal"
    if leaf in {"currency", "currency_code", "price_currency"}:
        return "currency"
    if leaf in {"available", "available_for_sale", "is_available"}:
        return "boolean"
    if leaf in {"weight", "mass"}:
        return "weight"
    if leaf in {"height", "width", "depth", "length"}:
        return "length"
    if leaf in {"dimensions", "dimension", "size"}:
        return "dimensions"
    if leaf in {"color", "colour"}:
        return "color"
    if leaf in {"material", "fabric"}:
        return "material"
    if leaf == "date" or leaf.endswith("_date"):
        return "date"
    return None


def _alias_config(source_config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    configured = source_config.get("normalization_aliases")
    if not isinstance(configured, dict):
        return {}
    aliases: dict[str, dict[str, str]] = {}
    for group, values in configured.items():
        if not isinstance(group, str) or not isinstance(values, dict):
            continue
        normalized_values = {
            _choice_key(key): value.strip()
            for key, value in values.items()
            if isinstance(key, str) and isinstance(value, str) and value.strip()
        }
        if normalized_values:
            aliases[_choice_key(group)] = normalized_values
    return aliases


def _lower_confidence(left: Confidence, right: Confidence) -> Confidence:
    return left if _CONFIDENCE_ORDER[left] <= _CONFIDENCE_ORDER[right] else right


def _measurement_text(value: object) -> str | None:
    if isinstance(value, dict):
        raw_value = value.get("value")
        raw_unit = value.get("unit")
        number = _clean_scalar_text(raw_value)
        unit = _clean_scalar_text(raw_unit)
        if number is None or unit is None:
            return None
        canonical_unit = _UNIT_ALIASES.get(unit.casefold(), unit.casefold())
        return f"{number} {canonical_unit}"
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return _clean_scalar_text(value)
        return _measurement_text(decoded)
    return _clean_scalar_text(value)


def _clean_scalar_text(value: object) -> str | None:
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip()
        return text or None
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return str(value)
    return None


def _choice_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")
