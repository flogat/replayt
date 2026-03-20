"""Normalize LLM-related numeric settings from defaults, YAML, and JSON."""

from __future__ import annotations

from typing import Any


def coerce_temperature(value: Any, *, default: float = 0.0) -> float:
    """Parse temperature; rejects bool (Python bool is a subclass of int)."""

    if value is None:
        return float(default)
    if isinstance(value, bool):
        raise TypeError("temperature cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return float(default)
        return float(s)
    return float(value)


def coerce_timeout_seconds(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("timeout_seconds cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("timeout_seconds cannot be empty")
        return float(s)
    return float(value)


def coerce_max_tokens_for_api(value: Any) -> int | None:
    """Return a non-negative int for the HTTP client, or None to omit max_tokens.

    Accepts int, floats (rounded), or numeric strings (e.g. from JSON merges).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return max(0, int(round(value)))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        return max(0, int(round(float(s))))
    raise TypeError(f"max_tokens must be numeric or numeric string, got {type(value).__name__}")
