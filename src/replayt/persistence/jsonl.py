from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from replayt.exceptions import LogLockError

_log = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_LOCK_HELP = (
    "Use a single writer per run_id, close other processes using this log, or retry. "
    "On Windows, another process may be holding the JSONL lock."
)


if os.name == "nt":  # pragma: no cover
    import msvcrt

    @contextmanager
    def _lock_file(f, *, shared: bool = False) -> Iterator[None]:
        """Mutex-style lock using a single byte at offset 0.

        ``msvcrt.locking`` operates on a byte range from the current position.
        Locking just 1 byte at position 0 avoids issues where appended bytes
        fall outside the originally-locked range.
        """
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except OSError as e:
            raise LogLockError(f"Could not lock JSONL log file. {_LOCK_HELP}") from e
        try:
            yield
        finally:
            if not shared:
                f.flush()
                os.fsync(f.fileno())
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                _log.warning("Could not unlock JSONL file (Windows); lock may be stuck", exc_info=True)
else:
    import fcntl

    @contextmanager
    def _lock_file(f, *, shared: bool = False) -> Iterator[None]:
        op = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(f.fileno(), op)
        except OSError as e:
            raise LogLockError(f"Could not lock JSONL log file. {_LOCK_HELP}") from e
        try:
            yield
        finally:
            if not shared:
                f.flush()
                os.fsync(f.fileno())
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                _log.warning("Could not unlock JSONL file; lock may be stuck", exc_info=True)


def _validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be 1-128 chars and contain only letters, numbers, dot, underscore, or hyphen")
    return run_id


def validate_run_id(run_id: str) -> str:
    """Return *run_id* if it is safe for JSONL basenames and store APIs (same rules as :class:`JSONLStore`)."""

    return _validate_run_id(run_id)


class JSONLStore:
    """Append-only JSONL per run under a base directory."""

    def __init__(self, base_dir: Path, *, create: bool = True) -> None:
        self.base_dir = base_dir
        if create:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe_run_id = _validate_run_id(run_id)
        return self.base_dir / f"{safe_run_id}.jsonl"

    def _ensure_path(self, run_id: str) -> Path:
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size == 0:
            path.write_bytes(b"\n")
        return path

    def _max_seq_full_scan(self, f) -> int:
        """Scan from BOF for the maximum ``seq`` (used when tail parsing cannot read a valid last line)."""

        f.seek(0)
        max_seq = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                max_seq = max(max_seq, int(event.get("seq", 0)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return max_seq

    def _read_last_seq_locked(self, f) -> int:
        """Return the last event seq by reading from EOF backward (O(tail)), not a full-file scan."""
        f.seek(0, os.SEEK_END)
        end = f.tell()
        if end == 0:
            return 0
        read_size = min(65536, end)
        start = end - read_size
        while True:
            f.seek(start)
            block = f.read(end - start)
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if lines:
                try:
                    event = json.loads(lines[-1])
                    return int(event.get("seq", 0))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            if start == 0:
                for line in reversed(lines[:-1] if len(lines) > 1 else []):
                    try:
                        event = json.loads(line)
                        return int(event.get("seq", 0))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                return self._max_seq_full_scan(f) if end > 0 else 0
            read_size = min(read_size * 2, end)
            start = end - read_size

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
        with path.open("r", encoding="utf-8") as f:
            with _lock_file(f, shared=True):
                f.seek(0)
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise RuntimeError(
                            f"Corrupted JSONL event log for run_id={run_id!r} at line {lineno}"
                        ) from e
        return out

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self.base_dir.glob("*.jsonl"))

    def delete_run(self, run_id: str) -> int:
        """Delete the JSONL file for *run_id*. Returns the freed size in bytes."""
        path = self._path(run_id)
        if not path.is_file():
            return 0
        size = path.stat().st_size
        path.unlink()
        return size
