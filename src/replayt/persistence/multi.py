from __future__ import annotations

from typing import Any

from replayt.persistence.base import EventStore


class MultiStore:
    """Write-through to multiple stores; reads come from the first store."""

    def __init__(self, primary: EventStore, *mirror: EventStore) -> None:
        self._all = (primary, *mirror)

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        for s in self._all:
            s.append(run_id, event)

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._all[0].load_events(run_id)
