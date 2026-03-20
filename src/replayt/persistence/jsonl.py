from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


if os.name == "nt":  # pragma: no cover
    import msvcrt

    @contextmanager
    def _lock_file(f) -> Iterator[None]:
        f.seek(0)
        length = max(f.seek(0, os.SEEK_END), 1)
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, length)
        try:
            yield
        finally:
            f.flush()
            os.fsync(f.fileno())
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, length)
else:
    import fcntl

    @contextmanager
    def _lock_file(f) -> Iterator[None]:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be 1-128 chars and contain only letters, numbers, dot, underscore, or hyphen")
    return run_id


class JSONLStore:
    """Append-only JSONL per run under a base directory."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe_run_id = _validate_run_id(run_id)
        return self.base_dir / f"{safe_run_id}.jsonl"

    def _ensure_path(self, run_id: str) -> Path:
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def _read_last_seq_locked(self, f) -> int:
        f.seek(0)
        last_seq = 0
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            event = json.loads(line)
            last_seq = max(last_seq, int(event.get("seq", 0)))
        return last_seq

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._ensure_path(run_id)
        with path.open("a+", encoding="utf-8") as f:
            with _lock_file(f):
                seq = self._read_last_seq_locked(f) + 1
                event = {"ts": ts, "run_id": run_id, "seq": seq, "type": typ, "payload": payload}
                f.seek(0, os.SEEK_END)
                f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
                return event

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        path = self._ensure_path(run_id)
        seq = int(event["seq"])
        line = json.dumps(event, default=str, ensure_ascii=False)
        with path.open("a+", encoding="utf-8") as f:
            with _lock_file(f):
                last_seq = self._read_last_seq_locked(f)
                if seq <= last_seq:
                    raise RuntimeError(
                        f"Out-of-order event sequence for run_id={run_id!r}: seq={seq} last_seq={last_seq}"
                    )
                f.seek(0, os.SEEK_END)
                f.write(line + "\n")

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._path(run_id)
        if not path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"Corrupted JSONL event log for run_id={run_id!r} at line {lineno}") from e
        return out

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self.base_dir.glob("*.jsonl"))
