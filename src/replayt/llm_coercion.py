"""Normalize LLM-related numeric settings from defaults, YAML, and JSON."""

from __future__ import annotations

import math
from typing import Any

# OpenAI-compatible chat APIs accept up to four stop sequences; cap string length to keep logs bounded.
_MAX_LLM_STOP_SLOTS = 4
_MAX_LLM_STOP_STR_CHARS = 512


def coerce_llm_stop_sequences(value: Any) -> list[str] | None:
    """Normalize ``stop`` for OpenAI-style ``/chat/completions`` (omit from JSON when ``None``)."""

    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return None if not s else [s]
    if isinstance(value, (list, tuple)):
        seqs: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"stop sequences must be strings, got {type(item).__name__}")
            t = item.strip()
            if t:
                seqs.append(t)
        if not seqs:
            return None
    else:
        raise TypeError(f"stop must be str, list, or tuple, got {type(value).__name__}")
    if len(seqs) > _MAX_LLM_STOP_SLOTS:
        raise ValueError(f"at most {_MAX_LLM_STOP_SLOTS} stop sequences allowed, got {len(seqs)}")
    for i, s in enumerate(seqs):
        if len(s) > _MAX_LLM_STOP_STR_CHARS:
            raise ValueError(
                f"stop sequence [{i}] length {len(s)} exceeds max {_MAX_LLM_STOP_STR_CHARS} characters"
            )
    return seqs


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


def coerce_top_p(value: Any) -> float | None:
    """Return ``top_p`` as a float in ``[0, 1]`` or ``None`` to omit it."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("top_p cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        out = float(s)
    else:
        out = float(value)
    if out < 0 or out > 1:
        raise ValueError(f"top_p must be between 0 and 1 inclusive, got {out}")
    return out


def coerce_openai_penalty(value: Any) -> float | None:
    """``frequency_penalty`` / ``presence_penalty`` for OpenAI-compatible APIs (range ``[-2, 2]``).

    ``None`` means omit the field from the HTTP payload (provider default).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("penalty cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        out = float(s)
    else:
        out = float(value)
    if out < -2.0 or out > 2.0:
        raise ValueError(f"penalty must be between -2 and 2 inclusive, got {out}")
    return out


def coerce_llm_seed(value: Any) -> int | None:
    """Optional integer ``seed`` for providers that support deterministic sampling."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("seed cannot be a boolean")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        return int(s, 10)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"seed must be a whole number, got {value}")
        return int(value)
    return int(value)


def coerce_max_tokens_for_api(value: Any) -> int | None:
    """Return a non-negative int for the HTTP client, or None to omit max_tokens.

    Accepts int, floats (rounded), or numeric strings (e.g. from JSON merges).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("max_tokens cannot be a boolean")
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("max_tokens must be a finite number")
        return max(0, int(round(value)))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            x = float(s)
        except ValueError as exc:
            raise ValueError(f"max_tokens must be numeric, got {s!r}") from exc
        if not math.isfinite(x):
            raise ValueError("max_tokens must be a finite number")
        return max(0, int(round(x)))
    raise TypeError(f"max_tokens must be numeric or numeric string, got {type(value).__name__}")
