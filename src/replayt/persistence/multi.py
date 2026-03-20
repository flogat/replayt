from __future__ import annotations

import logging
from typing import Any

from replayt.persistence.base import EventStore

_log = logging.getLogger("replayt.persistence")


class MultiStore:
    """Write-through to multiple stores; reads come from the first store."""

    def __init__(self, primary: EventStore, *mirror: EventStore) -> None:
        self._primary = primary
        self._mirror = mirror
        self._all = (primary, *mirror)

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._primary.append_event(run_id, ts=ts, typ=typ, payload=payload)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception:  # noqa: BLE001
                _log.warning("Mirror store write failed for run_id=%s", run_id, exc_info=True)
        return event

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        self._primary.append(run_id, event)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception:  # noqa: BLE001
                _log.warning("Mirror store append failed for run_id=%s", run_id, exc_info=True)

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._primary.load_events(run_id)

    def list_run_ids(self) -> list[str]:
        return self._primary.list_run_ids()
