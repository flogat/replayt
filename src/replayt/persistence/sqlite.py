from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from replayt.persistence.jsonl import _validate_run_id


class SQLiteStore:
    """SQLite-backed event store.

    .. warning::
        ``SQLiteStore`` is **not thread-safe**. Each thread must use its own
        instance, or external synchronisation must be provided.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cx = sqlite3.connect(db_path)
        self._init_db()

    def close(self) -> None:
        self._cx.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_db(self) -> None:
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              run_id TEXT NOT NULL,
              seq INTEGER NOT NULL,
              type TEXT NOT NULL,
              ts TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY (run_id, seq)
            )
            """
        )
        self._cx.commit()

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = _validate_run_id(run_id)
        payload_json = json.dumps(payload, default=str)
        self._cx.execute("BEGIN IMMEDIATE")
        seq = int(
            self._cx.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        self._cx.execute(
            "INSERT INTO events (run_id, seq, type, ts, payload_json) VALUES (?,?,?,?,?)",
            (run_id, seq, typ, ts, payload_json),
        )
        self._cx.commit()
        return {"ts": ts, "run_id": run_id, "seq": seq, "type": typ, "payload": payload}

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        run_id = _validate_run_id(run_id)
        seq = int(event["seq"])
        typ = str(event["type"])
        ts = str(event["ts"])
        payload = json.dumps(event.get("payload", {}), default=str)
        try:
            self._cx.execute(
                "INSERT INTO events (run_id, seq, type, ts, payload_json) VALUES (?,?,?,?,?)",
                (run_id, seq, typ, ts, payload),
            )
        except sqlite3.IntegrityError as e:
            raise RuntimeError(f"Duplicate event sequence for run_id={run_id!r}: seq={seq}") from e
        self._cx.commit()

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        run_id = _validate_run_id(run_id)
        rows = self._cx.execute(
            "SELECT seq, type, ts, payload_json FROM events WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for seq, typ, ts, payload_json in rows:
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Corrupted SQLite event payload for run_id={run_id!r} seq={seq}"
                ) from e
            events.append(
                {
                    "seq": seq,
                    "type": typ,
                    "ts": ts,
                    "run_id": run_id,
                    "payload": payload,
                }
            )
        return events

    def list_run_ids(self) -> list[str]:
        rows = self._cx.execute("SELECT DISTINCT run_id FROM events ORDER BY run_id").fetchall()
        return [str(row[0]) for row in rows]

    def delete_run(self, run_id: str) -> int:
        """Delete all events for *run_id*. Returns the number of rows deleted."""
        run_id = _validate_run_id(run_id)
        cursor = self._cx.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        self._cx.commit()
        return cursor.rowcount
