from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from replayt.persistence.base import EventStore

_log = logging.getLogger("replayt.persistence")

MirrorErrorHandler = Callable[[str, EventStore, Exception], None]


class MultiStore:
    """Write-through to multiple stores; reads come from the first store.

    Mirror store failures are logged at WARNING level.  Pass *on_mirror_error*
    to receive a callback ``(operation, store, exception)`` for alerting or
    metrics.
    """

    def __init__(
        self,
        primary: EventStore,
        *mirror: EventStore,
        on_mirror_error: MirrorErrorHandler | None = None,
    ) -> None:
        self._primary = primary
        self._mirror = mirror
        self._all = (primary, *mirror)
        self._on_mirror_error = on_mirror_error
        self.mirror_error_count: int = 0

    def _handle_mirror_error(self, operation: str, store: EventStore, exc: Exception, run_id: str) -> None:
        self.mirror_error_count += 1
        _log.warning("Mirror store %s failed for run_id=%s", operation, run_id, exc_info=True)
        if self._on_mirror_error is not None:
            self._on_mirror_error(operation, store, exc)

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._primary.append_event(run_id, ts=ts, typ=typ, payload=payload)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("append_event", store, exc, run_id)
        return event

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        self._primary.append(run_id, event)
        for store in self._mirror:
            try:
                store.append(run_id, event)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("append", store, exc, run_id)

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._primary.load_events(run_id)

    def list_run_ids(self) -> list[str]:
        return self._primary.list_run_ids()

    def delete_run(self, run_id: str) -> int:
        result = self._primary.delete_run(run_id)
        for store in self._mirror:
            try:
                store.delete_run(run_id)
            except Exception as exc:  # noqa: BLE001
                self._handle_mirror_error("delete_run", store, exc, run_id)
        return result
