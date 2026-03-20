from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


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

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        path = self._path(run_id)
        line = json.dumps(event, default=str, ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._path(run_id)
        if not path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def list_run_ids(self) -> list[str]:
        return sorted(path.stem for path in self.base_dir.glob("*.jsonl"))
