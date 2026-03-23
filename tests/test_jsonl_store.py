from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from replayt.persistence import JSONLStore, validate_run_id
from replayt.persistence.jsonl import resolve_jsonl_posix_new_file_mode_from_env


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


def test_jsonl_append_event_monotonic_seq_after_non_object_json_tail(tmp_path: Path) -> None:
    path = tmp_path / "nonobj_tail.jsonl"
    path.write_text(
        '{"ts":"t","run_id":"nonobj_tail","seq":1,"type":"run_started","payload":{}}\n'
        '{"ts":"t","run_id":"nonobj_tail","seq":2,"type":"state_entered","payload":{}}\n'
        "[1,2,3]\n",
        encoding="utf-8",
    )
    store = JSONLStore(tmp_path)
    ev = store.append_event("nonobj_tail", ts="t3", typ="state_entered", payload={})
    assert ev["seq"] == 3


def test_jsonl_append_event_monotonic_seq_after_non_numeric_seq_tail(tmp_path: Path) -> None:
    """Tail line may be a JSON object with an unusable ``seq`` (mirrors full-scan tolerance)."""

    path = tmp_path / "badseq_tail.jsonl"
    path.write_text(
        '{"ts":"t","run_id":"badseq_tail","seq":1,"type":"run_started","payload":{}}\n'
        '{"ts":"t","run_id":"badseq_tail","seq":2,"type":"state_entered","payload":{}}\n'
        '{"ts":"t","run_id":"badseq_tail","seq":"nope","type":"state_entered","payload":{}}\n',
        encoding="utf-8",
    )
    store = JSONLStore(tmp_path)
    ev = store.append_event("badseq_tail", ts="t3", typ="state_entered", payload={})
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


def test_jsonl_store_raises_for_non_object_line(tmp_path: Path) -> None:
    path = tmp_path / "arr.jsonl"
    path.write_text(
        '{"ts":"t","run_id":"arr","seq":1,"type":"run_started","payload":{}}\n'
        '[1,2,3]\n',
        encoding="utf-8",
    )
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match="JSON object"):
        store.load_events("arr")


def test_jsonl_store_raises_for_truncated_line(tmp_path: Path) -> None:
    path = tmp_path / "trunc.jsonl"
    path.write_text('{"seq": 1, "run_id": "trunc", "type": "run_started", "ts": "t", "payload":', encoding="utf-8")
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match="Corrupted JSONL"):
        store.load_events("trunc")


def test_jsonl_store_raises_for_invalid_utf8_on_load(tmp_path: Path) -> None:
    path = tmp_path / "badenc.jsonl"
    path.write_bytes(b"\xff\xfe\x00")
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match=r"Corrupted JSONL.*not valid UTF-8"):
        store.load_events("badenc")


def test_jsonl_append_event_raises_for_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "badappend.jsonl"
    path.write_bytes(b"\xff")
    store = JSONLStore(tmp_path)
    with pytest.raises(RuntimeError, match=r"Corrupted JSONL.*not valid UTF-8"):
        store.append_event("badappend", ts="t", typ="run_started", payload={})


def test_jsonl_load_events_opens_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JSONLStore(tmp_path)
    store.append_event("r1", ts="t1", typ="run_started", payload={})
    seen_modes: list[str] = []
    orig_open = Path.open

    def spy_open(self: Path, mode: str = "r", *args, **kwargs):
        if self == tmp_path / "r1.jsonl":
            seen_modes.append(mode)
        return orig_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)

    events = store.load_events("r1")

    assert len(events) == 1
    assert seen_modes == ["r"]


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod modes")
def test_jsonl_store_applies_posix_owner_only_mode_on_new_run_file(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path, posix_new_file_mode=0o600)
    store.append_event("r1", ts="t1", typ="run_started", payload={})
    mode = stat.S_IMODE((tmp_path / "r1.jsonl").stat().st_mode)
    assert mode == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod modes")
def test_jsonl_store_posix_mode_none_skips_chmod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, int]] = []
    real_chmod = os.chmod

    def spy_chmod(path: os.PathLike[str] | str, mode: int, /) -> None:
        calls.append((path, mode))
        return real_chmod(path, mode)

    monkeypatch.setattr(os, "chmod", spy_chmod)
    store = JSONLStore(tmp_path, posix_new_file_mode=None)
    store.append_event("r1", ts="t1", typ="run_started", payload={})
    assert calls == []


def test_resolve_jsonl_posix_new_file_mode_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLAYT_JSONL_POSIX_MODE", raising=False)
    if os.name == "nt":
        assert resolve_jsonl_posix_new_file_mode_from_env() is None
        return
    assert resolve_jsonl_posix_new_file_mode_from_env() == 0o600
    monkeypatch.setenv("REPLAYT_JSONL_POSIX_MODE", "inherit")
    assert resolve_jsonl_posix_new_file_mode_from_env() is None
    monkeypatch.setenv("REPLAYT_JSONL_POSIX_MODE", "660")
    assert resolve_jsonl_posix_new_file_mode_from_env() == 0o660
    monkeypatch.setenv("REPLAYT_JSONL_POSIX_MODE", "0o640")
    assert resolve_jsonl_posix_new_file_mode_from_env() == 0o640
