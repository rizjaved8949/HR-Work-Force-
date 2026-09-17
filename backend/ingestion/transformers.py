"""Explicit semantic value transformations for Step 6."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ontology.models import OntologyProperty

from .models import PropertyMapping


TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0"}


def _is_null(value: Any, mapping: PropertyMapping) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return any(text.casefold() == str(token).strip().casefold() for token in mapping.null_values)


def _parse_date(value: Any, date_format: str | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if date_format:
        return datetime.strptime(text, date_format).date()
    # Without an explicit source format only ISO is accepted; ambiguous dates are rejected.
    return date.fromisoformat(text)


def _parse_datetime(value: Any, date_format: str | None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if date_format:
        parsed = datetime.strptime(text, date_format)
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def transform_value(value: Any, prop: OntologyProperty, mapping: PropertyMapping) -> Any:
    if _is_null(value, mapping):
        return None

    data_type = prop.data_type
    if mapping.transform not in {"semantic_cast", "identity_string", "month_name_to_number"}:
        raise ValueError(f"Unsupported transform: {mapping.transform!r}")

    if mapping.transform == "month_name_to_number":
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        text = str(value).strip().casefold()
        if text in months:
            result = months[text]
        else:
            try:
                numeric = int(text)
            except ValueError as error:
                raise ValueError(f"Expected month name or month number; found {value!r}") from error
            if not 1 <= numeric <= 12:
                raise ValueError(f"Month number must be 1..12; found {numeric!r}")
            result = numeric
    elif mapping.transform == "identity_string":
        result: Any = str(value).strip()
    elif data_type == "string":
        result = str(value).strip()
    elif data_type == "integer":
        number = Decimal(str(value).strip())
        if number != number.to_integral_value():
            raise ValueError(f"Expected integer-compatible value; found {value!r}")
        result = int(number)
    elif data_type == "decimal":
        try:
            result = float(Decimal(str(value).strip()))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"Expected decimal-compatible value; found {value!r}") from error
    elif data_type == "boolean":
        if isinstance(value, bool):
            result = value
        else:
            text = str(value).strip().casefold()
            if text in TRUE_VALUES:
                result = True
            elif text in FALSE_VALUES:
                result = False
            else:
                raise ValueError(f"Expected boolean-compatible value; found {value!r}")
    elif data_type == "date":
        result = _parse_date(value, mapping.date_format)
    elif data_type in {"datetime", "timestamp"}:
        result = _parse_datetime(value, mapping.date_format)
    elif data_type in {"object", "json"}:
        result = value
    else:
        result = value

    if isinstance(result, (int, float)) and not isinstance(result, bool):
        if mapping.numeric_multiplier is not None:
            result = result * mapping.numeric_multiplier
        if mapping.numeric_divisor is not None:
            if mapping.numeric_divisor == 0:
                raise ValueError("numeric_divisor cannot be zero")
            result = result / mapping.numeric_divisor
        if data_type == "integer":
            if float(result).is_integer():
                result = int(result)
            else:
                raise ValueError("Numeric conversion produced a non-integer for integer ontology property")
    return result
