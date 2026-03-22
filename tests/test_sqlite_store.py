from __future__ import annotations

import sqlite3
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


def test_sqlite_append_event_rolls_back_failed_transaction(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store._cx.execute(
        """
        CREATE TRIGGER fail_boom
        BEFORE INSERT ON events
        WHEN NEW.type = 'boom'
        BEGIN
          SELECT RAISE(FAIL, 'boom trigger');
        END
        """
    )
    store._cx.commit()

    with pytest.raises(sqlite3.IntegrityError, match="boom trigger"):
        store.append_event("r1", ts="t1", typ="boom", payload={})

    event = store.append_event("r1", ts="t2", typ="run_started", payload={})

    assert event["seq"] == 1
    assert [saved["type"] for saved in store.load_events("r1")] == ["run_started"]


def test_sqlite_append_rolls_back_failed_transaction(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.append_event("r1", ts="t1", typ="run_started", payload={})

    with pytest.raises(RuntimeError, match="Duplicate event sequence"):
        store.append("r1", {"ts": "t1", "run_id": "r1", "seq": 1, "type": "dupe", "payload": {}})

    store.append("r1", {"ts": "t2", "run_id": "r1", "seq": 2, "type": "state_entered", "payload": {}})

    assert [saved["seq"] for saved in store.load_events("r1")] == [1, 2]


def test_multi_store_writes_both(tmp_path: Path) -> None:
    j = JSONLStore(tmp_path / "j")
    s = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(j, s)
    event = m.append_event("r2", ts="t", typ="run_started", payload={})
    assert event["seq"] == 1
    assert len(j.load_events("r2")) == 1
    assert len(s.load_events("r2")) == 1


def test_multi_store_close_closes_sqlite_mirror(tmp_path: Path) -> None:
    j = JSONLStore(tmp_path / "j")
    s = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(j, s)
    m.append_event("r1", ts="t", typ="run_started", payload={})
    m.close()
    with pytest.raises(sqlite3.ProgrammingError):
        s._cx.execute("SELECT 1")


def test_multi_store_close_calls_primary_close_when_present(tmp_path: Path) -> None:
    closed: list[str] = []

    class _PrimaryWithClose(JSONLStore):
        def close(self) -> None:
            closed.append("primary")

    primary = _PrimaryWithClose(tmp_path / "jp")
    mirror = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(primary, mirror)
    m.append_event("r1", ts="t", typ="run_started", payload={})
    m.close()
    assert closed == ["primary"]
    with pytest.raises(sqlite3.ProgrammingError):
        mirror._cx.execute("SELECT 1")


def test_sqlite_load_events_corrupt_payload_includes_seq(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    store = SQLiteStore(db)
    store.close()
    cx = sqlite3.connect(db)
    cx.execute(
        "INSERT INTO events (run_id, seq, type, ts, payload_json) VALUES (?,?,?,?,?)",
        ("r1", 1, "x", "t", "NOT JSON"),
    )
    cx.commit()
    cx.close()
    reader = SQLiteStore(db)
    with pytest.raises(RuntimeError) as exc_info:
        reader.load_events("r1")
    assert "Corrupted SQLite event payload" in str(exc_info.value)
    assert "seq=1" in str(exc_info.value)


def test_sqlite_store_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "events.db")

    with pytest.raises(ValueError, match="run_id"):
        store.append("../escape", {"seq": 1, "type": "x", "ts": "now", "payload": {}})

    with pytest.raises(ValueError, match="run_id"):
        store.load_events("../escape")


def test_sqlite_delete_run(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.append_event("r1", ts="t1", typ="run_started", payload={})
    store.append_event("r1", ts="t2", typ="state_entered", payload={})
    assert len(store.load_events("r1")) == 2
    deleted = store.delete_run("r1")
    assert deleted == 2
    assert store.load_events("r1") == []
    assert "r1" not in store.list_run_ids()


def test_sqlite_read_only_store_loads_existing_events_and_rejects_writes(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    writer = SQLiteStore(db)
    writer.append_event("r1", ts="t1", typ="run_started", payload={})
    writer.close()

    reader = SQLiteStore(db, read_only=True)
    try:
        assert [event["type"] for event in reader.load_events("r1")] == ["run_started"]
        with pytest.raises(RuntimeError, match="read-only"):
            reader.append_event("r1", ts="t2", typ="state_entered", payload={})
    finally:
        reader.close()


def test_multi_store_delete_run(tmp_path: Path) -> None:
    j = JSONLStore(tmp_path / "j")
    s = SQLiteStore(tmp_path / "db.sqlite3")
    m = MultiStore(j, s)
    m.append_event("r1", ts="t", typ="run_started", payload={})
    assert len(j.load_events("r1")) == 1
    assert len(s.load_events("r1")) == 1
    m.delete_run("r1")
    assert j.load_events("r1") == []
    assert s.load_events("r1") == []


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


def test_sqlite_store_context_manager(tmp_path: Path) -> None:
    db = tmp_path / "ctx.sqlite3"
    with SQLiteStore(db) as store:
        store.append_event("r1", ts="t1", typ="run_started", payload={})
        assert len(store.load_events("r1")) == 1
    with pytest.raises(Exception):
        store.load_events("r1")


def test_multi_store_on_mirror_error_callback(tmp_path: Path) -> None:
    primary = JSONLStore(tmp_path / "primary")
    errors: list[tuple[str, Exception]] = []

    def on_error(op: str, _store, exc: Exception) -> None:
        errors.append((op, exc))

    class _FailingStore:
        def append_event(self, run_id, *, ts, typ, payload):
            raise RuntimeError("boom")

        def append(self, run_id, event):
            raise RuntimeError("boom")

        def load_events(self, run_id):
            return []

        def list_run_ids(self):
            return []

        def delete_run(self, run_id):
            raise RuntimeError("boom")

    m = MultiStore(primary, _FailingStore(), on_mirror_error=on_error)
    m.append_event("r1", ts="t", typ="run_started", payload={})
    assert len(errors) == 1
    assert errors[0][0] == "append_event"
    assert m.mirror_error_count == 1

    m.delete_run("r1")
    assert m.mirror_error_count == 2
