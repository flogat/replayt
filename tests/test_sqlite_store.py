from __future__ import annotations

from pathlib import Path

import pytest

from replayt.persistence import JSONLStore, MultiStore, SQLiteStore


def test_sqlite_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    store = SQLiteStore(db)
    store.append(
        "r1",
        {"ts": "t", "run_id": "r1", "seq": 1, "type": "run_started", "payload": {"workflow_name": "x"}},
    )
    ev = store.load_events("r1")
    assert len(ev) == 1
    assert ev[0]["type"] == "run_started"


def test_sqlite_append_event_allocates_monotonic_sequence(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    first = store.append_event("r1", ts="t1", typ="run_started", payload={})
    second = store.append_event("r1", ts="t2", typ="state_entered", payload={})
    assert first["seq"] == 1
    assert second["seq"] == 2


def test_multi_store_writes_both(tmp_path: Path) -> None:
    j = JSONLStore(tmp_path / "j")
    s = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(j, s)
    event = m.append_event("r2", ts="t", typ="run_started", payload={})
    assert event["seq"] == 1
    assert len(j.load_events("r2")) == 1
    assert len(s.load_events("r2")) == 1


def test_sqlite_store_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db")

    with pytest.raises(ValueError, match="run_id"):
        store.append("../escape", {"seq": 1, "type": "x", "ts": "now", "payload": {}})

    with pytest.raises(ValueError, match="run_id"):
        store.load_events("../escape")


def test_multi_store_append_catches_mirror_failures(tmp_path: Path) -> None:
    primary = JSONLStore(tmp_path / "primary")

    class _FailingStore:
        def append_event(self, run_id, *, ts, typ, payload):
            raise RuntimeError("boom")

        def append(self, run_id, event):
            raise RuntimeError("boom")

        def load_events(self, run_id):
            return []

        def list_run_ids(self):
            return []

    m = MultiStore(primary, _FailingStore())
    event = m.append_event("r1", ts="t", typ="run_started", payload={})
    assert event["seq"] == 1
    assert len(primary.load_events("r1")) == 1

    m.append("r1", {"ts": "t2", "run_id": "r1", "seq": 2, "type": "state_entered", "payload": {}})
    assert len(primary.load_events("r1")) == 2
