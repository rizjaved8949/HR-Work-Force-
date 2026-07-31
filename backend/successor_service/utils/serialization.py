from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def clean_record(record: dict) -> dict:
    return {str(key): clean_value(value) for key, value in record.items()}


def clean_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_payload(item) for item in value]
    return clean_value(value)
