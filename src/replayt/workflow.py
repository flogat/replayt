from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from replayt.types import RetryPolicy

F = TypeVar("F", bound=Callable[..., Any])


class Workflow:
    """Finite-state workflow definition with explicit handlers and optional metadata."""

    def __init__(self, name: str, *, version: str = "1") -> None:
        self.name = name
        self.version = version
        self.initial_state: str | None = None
        self._steps: dict[str, Callable[..., Any]] = {}
        self._retries: dict[str, RetryPolicy] = {}
        self._edges: list[tuple[str, str]] = []

    def set_initial(self, state: str) -> None:
        self.initial_state = state

    def step(self, name: str, *, retries: RetryPolicy | None = None) -> Callable[[F], F]:
        def deco(fn: F) -> F:
            self._steps[name] = fn
            if retries is not None:
                self._retries[name] = retries
            return fn

        return deco

    def get_handler(self, name: str) -> Callable[..., Any]:
        if name not in self._steps:
            raise KeyError(f"Unknown step/state: {name}")
        return self._steps[name]

    def retry_policy_for(self, name: str) -> RetryPolicy:
        return self._retries.get(name, RetryPolicy())

    def step_names(self) -> list[str]:
        return sorted(self._steps.keys())

    def note_transition(self, from_state: str, to_state: str) -> None:
        """Optional documentation edge for `replayt graph` or validation."""

        edge = (from_state, to_state)
        if edge not in self._edges:
            self._edges.append(edge)

    def edges(self) -> list[tuple[str, str]]:
        return list(self._edges)

    def allows_transition(self, from_state: str, to_state: str | None) -> bool:
        if to_state in (None, ""):
            return True
        if not self._edges:
            return True
        return (from_state, to_state) in self._edges
