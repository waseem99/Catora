from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

Quantity = Literal["length", "mass"]
type ScalarValue = str | int | float | bool | None
type NormalizedValue = ScalarValue | dict[str, ScalarValue] | list[ScalarValue]

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
_TRUE_VALUES = frozenset({"true", "yes", "y", "1", "on"})
_FALSE_VALUES = frozenset({"false", "no", "n", "0", "off"})
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class ParsedValue:
    value: NormalizedValue
    value_type: str
    unit: str | None = None
    confidence: Literal["high", "medium", "low"] = "high"
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
    text = _clean_scalar_text(value)
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
    normalized_parts: list[dict[str, ScalarValue]] = []
    for index, part in enumerate(parts):
        candidate = part if index == len(parts) - 1 else f"{part} {shared_unit}"
        normalized = normalize_measurement(candidate, expected_quantity="length")
        if normalized is None or not isinstance(normalized.value, dict):
            return None
        normalized_parts.append(normalized.value)

    return ParsedValue(
        value={
            "raw": text,
            "quantity": "dimensions",
            "canonical_unit": "mm",
            "canonical_values": [
                str(part["canonical_value"]) for part in normalized_parts
            ],
            "source_unit": shared_unit.casefold(),
        },
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
    if normalized_hint in {"length", "distance"}:
        return normalize_measurement(value, expected_quantity="length")
    if normalized_hint in {"mass", "weight"}:
        return normalize_measurement(value, expected_quantity="mass")
    if normalized_hint in {"dimensions", "dimension"}:
        return normalize_dimensions(value)
    if normalized_hint in {"decimal", "price", "number"}:
        return normalize_decimal(value)
    if aliases is not None and normalized_hint:
        return normalize_choice(
            value,
            aliases=aliases,
            value_type=normalized_hint,
        )
    return None


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
