from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from replayt.persistence.jsonl import _validate_run_id


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as cx:
            cx.execute(
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
            cx.commit()

    def append_event(self, run_id: str, *, ts: str, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = _validate_run_id(run_id)
        payload_json = json.dumps(payload, default=str)
        with self._connect() as cx:
            cx.execute("BEGIN IMMEDIATE")
            seq = int(
                cx.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            cx.execute(
                "INSERT INTO events (run_id, seq, type, ts, payload_json) VALUES (?,?,?,?,?)",
                (run_id, seq, typ, ts, payload_json),
            )
            cx.commit()
        return {"ts": ts, "run_id": run_id, "seq": seq, "type": typ, "payload": payload}

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        run_id = _validate_run_id(run_id)
        seq = int(event["seq"])
        typ = str(event["type"])
        ts = str(event["ts"])
        payload = json.dumps(event.get("payload", {}), default=str)
        with self._connect() as cx:
            try:
                cx.execute(
                    "INSERT INTO events (run_id, seq, type, ts, payload_json) VALUES (?,?,?,?,?)",
                    (run_id, seq, typ, ts, payload),
                )
            except sqlite3.IntegrityError as e:
                raise RuntimeError(f"Duplicate event sequence for run_id={run_id!r}: seq={seq}") from e
            cx.commit()

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        run_id = _validate_run_id(run_id)
        with self._connect() as cx:
            rows = cx.execute(
                "SELECT seq, type, ts, payload_json FROM events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for seq, typ, ts, payload_json in rows:
            events.append(
                {
                    "seq": seq,
                    "type": typ,
                    "ts": ts,
                    "run_id": run_id,
                    "payload": json.loads(payload_json),
                }
            )
        return events

    def list_run_ids(self) -> list[str]:
        with self._connect() as cx:
            rows = cx.execute("SELECT DISTINCT run_id FROM events ORDER BY run_id").fetchall()
        return [str(row[0]) for row in rows]
