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


def test_multi_store_writes_both(tmp_path: Path) -> None:
    j = JSONLStore(tmp_path / "j")
    s = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(j, s)
    m.append(
        "r2",
        {"ts": "t", "run_id": "r2", "seq": 1, "type": "run_started", "payload": {}},
    )
    assert len(j.load_events("r2")) == 1
    assert len(s.load_events("r2")) == 1


def test_sqlite_store_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    from replayt.persistence.sqlite import SQLiteStore

    store = SQLiteStore(tmp_path / "events.db")

    with pytest.raises(ValueError, match="run_id"):
        store.append("../escape", {"seq": 1, "type": "x", "ts": "now", "payload": {}})

    with pytest.raises(ValueError, match="run_id"):
        store.load_events("../escape")
