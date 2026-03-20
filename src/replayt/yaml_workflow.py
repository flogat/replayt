from __future__ import annotations

from pathlib import Path
from typing import Any

from replayt.workflow import Workflow


def load_workflow_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover
        msg = "Install replayt with the `yaml` extra: pip install replayt[yaml]"
        raise RuntimeError(msg) from e
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a mapping")
    return raw


def workflow_from_spec(spec: dict[str, Any]) -> Workflow:
    """Minimal declarative skeleton. Handlers must still be attached in Python."""

    name = str(spec.get("name", "workflow"))
    wf = Workflow(name)
    wf.set_initial(str(spec["initial"]))
    edges = spec.get("edges") or []
    if isinstance(edges, list):
        for e in edges:
            if isinstance(e, dict) and "from" in e and "to" in e:
                wf.note_transition(str(e["from"]), str(e["to"]))
    return wf
