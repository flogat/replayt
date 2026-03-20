from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LogMode(str, Enum):
    """How much LLM traffic to persist."""

    redacted = "redacted"
    full = "full"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.0
