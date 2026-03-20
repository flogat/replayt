from __future__ import annotations

from pathlib import Path

import pytest

from replayt.persistence import JSONLStore, validate_run_id


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    store.append(
        "r1",
        {"ts": "t", "run_id": "r1", "seq": 1, "type": "run_started", "payload": {"workflow_name": "x"}},
    )
    events = store.load_events("r1")
    assert len(events) == 1
    assert events[0]["type"] == "run_started"


def test_jsonl_append_event_allocates_monotonic_sequence(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    first = store.append_event("r1", ts="t1", typ="run_started", payload={})
    second = store.append_event("r1", ts="t2", typ="state_entered", payload={})
    assert first["seq"] == 1
    assert second["seq"] == 2


def test_jsonl_append_event_monotonic_seq_after_corrupt_tail_line(tmp_path: Path) -> None:
    path = tmp_path / "corrupt_tail.jsonl"
    path.write_text(
        '{"ts":"t","run_id":"corrupt_tail","seq":1,"type":"run_started","payload":{}}\n'
        '{"ts":"t","run_id":"corrupt_tail","seq":2,"type":"state_entered","payload":{}}\n'
        "NOT_JSON_TAIL\n",
        encoding="utf-8",
    )
    store = JSONLStore(tmp_path)
    ev = store.append_event("corrupt_tail", ts="t3", typ="state_entered", payload={})
    assert ev["seq"] == 3


def test_jsonl_append_event_tail_seq_on_long_log(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    rid = "longrun"
    for i in range(40):
        store.append_event(rid, ts=f"t{i}", typ="state_entered", payload={"i": i})
    last = store.append_event(rid, ts="tlast", typ="run_completed", payload={"status": "completed"})
    assert last["seq"] == 41


def test_jsonl_store_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)

    with pytest.raises(ValueError, match="run_id"):
        store.append("../escape", {"seq": 1, "type": "x", "ts": "now", "payload": {}})

    with pytest.raises(ValueError, match="run_id"):
        store.load_events("../escape")


def test_jsonl_store_raises_for_corruption(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"seq": 1}\nnot-json\n', encoding="utf-8")
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match="Corrupted JSONL"):
        store.load_events("bad")


def test_jsonl_store_raises_for_truncated_line(tmp_path: Path) -> None:
    path = tmp_path / "trunc.jsonl"
    path.write_text('{"seq": 1, "run_id": "trunc", "type": "run_started", "ts": "t", "payload":', encoding="utf-8")
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match="Corrupted JSONL"):
        store.load_events("trunc")


def test_jsonl_delete_run(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    store.append_event("r1", ts="t1", typ="run_started", payload={})
    assert len(store.load_events("r1")) == 1
    freed = store.delete_run("r1")
    assert freed > 0
    assert store.load_events("r1") == []
    assert "r1" not in store.list_run_ids()


def test_jsonl_delete_run_missing(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    freed = store.delete_run("nonexistent")
    assert freed == 0


def test_validate_run_id_accepts_safe_ids() -> None:
    assert validate_run_id("ab") == "ab"
    assert validate_run_id("a-b_1.c") == "a-b_1.c"


def test_validate_run_id_rejects_unsafe_ids() -> None:
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id("../x")
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id("x/y")
