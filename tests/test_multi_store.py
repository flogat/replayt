from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from replayt.persistence import JSONLStore, MultiStore


class _FailingMirror:
    """Minimal store that fails on mirror append only."""

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        raise RuntimeError("mirror append failed")

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return []

    def list_run_ids(self) -> list[str]:
        return []

    def delete_run(self, run_id: str) -> int:
        return 0


def test_multi_store_strict_mirror_raises_after_primary_write(tmp_path: Path) -> None:
    primary = JSONLStore(tmp_path)
    multi = MultiStore(primary, _FailingMirror(), strict_mirror=True)
    with pytest.raises(RuntimeError, match="mirror append failed"):
        multi.append_event("run1", ts="t", typ="run_started", payload={})


def test_multi_store_lenient_mirror_logs_and_continues(tmp_path: Path) -> None:
    primary = JSONLStore(tmp_path)
    multi = MultiStore(primary, _FailingMirror(), strict_mirror=False)
    ev = multi.append_event("run1", ts="t", typ="run_started", payload={})
    assert ev["seq"] == 1
    assert multi.mirror_error_count == 1
