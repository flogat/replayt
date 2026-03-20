from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventStore(Protocol):
    def append(self, run_id: str, event: dict[str, Any]) -> None: ...

    def load_events(self, run_id: str) -> list[dict[str, Any]]: ...
