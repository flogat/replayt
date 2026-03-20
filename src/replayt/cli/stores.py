"""JSONL / SQLite store construction and read helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from replayt.persistence import JSONLStore, MultiStore, SQLiteStore


def make_store(log_dir: Path, sqlite: Path | None, *, strict_mirror: bool = False) -> JSONLStore | MultiStore:
    log_dir.mkdir(parents=True, exist_ok=True)
    primary = JSONLStore(log_dir)
    if sqlite is None:
        return primary
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    return MultiStore(primary, SQLiteStore(sqlite), strict_mirror=strict_mirror)


@contextmanager
def read_store(log_dir: Path, sqlite: Path | None) -> Iterator[JSONLStore | SQLiteStore]:
    if sqlite is not None:
        store = SQLiteStore(sqlite)
        try:
            yield store
        finally:
            store.close()
    else:
        yield JSONLStore(log_dir)
