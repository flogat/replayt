from __future__ import annotations

from pathlib import Path

from replayt.persistence import JSONLStore


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    store.append(
        "r1",
        {"ts": "t", "run_id": "r1", "seq": 1, "type": "run_started", "payload": {"workflow_name": "x"}},
    )
    events = store.load_events("r1")
    assert len(events) == 1
    assert events[0]["type"] == "run_started"
