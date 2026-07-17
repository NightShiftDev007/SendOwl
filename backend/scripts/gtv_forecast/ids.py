"""Safe string IDs for snowflake-sized integers (never cast through float64)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def as_str_id(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() == "nan":
            return None
        if s.endswith(".0") and s[:-2].isdigit():
            return s[:-2]
        return s
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        # Only safe for small ints; large snowflake IDs must not arrive as float.
        if np.isfinite(value) and float(value).is_integer() and abs(value) < 2**53:
            return str(int(value))
        # Best-effort without claiming precision
        return format(value, ".0f")
    return str(value)


def series_str_id(s: pd.Series) -> pd.Series:
    return s.map(as_str_id)
