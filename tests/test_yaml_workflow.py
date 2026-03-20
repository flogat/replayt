from __future__ import annotations

from pathlib import Path

import pytest

from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec

yaml = pytest.importorskip("yaml")


def test_load_workflow_yaml(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        """
name: yaml-demo
initial: validate
edges:
  - from: validate
    to: done
""".strip(),
        encoding="utf-8",
    )

    spec = load_workflow_yaml(path)

    assert spec["name"] == "yaml-demo"
    assert spec["initial"] == "validate"
    assert spec["edges"] == [{"from": "validate", "to": "done"}]


def test_workflow_from_spec_records_declared_edges() -> None:
    wf = workflow_from_spec(
        {
            "name": "yaml-demo",
            "initial": "validate",
            "edges": [
                {"from": "validate", "to": "approved"},
                {"from": "approved", "to": "done"},
            ],
            "steps": {
                "validate": {"next": "approved"},
                "approved": {"next": "done"},
                "done": {"next": None},
            },
        }
    )

    assert wf.name == "yaml-demo"
    assert wf.initial_state == "validate"
    assert wf.edges() == [("validate", "approved"), ("approved", "done")]


def test_yaml_workflow_runs_without_python_handlers(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "yaml-runner",
            "initial": "ingest",
            "steps": {
                "ingest": {"require": ["ticket"], "set": {"stage": "ingested"}, "next": "branch"},
                "branch": {
                    "branch": {
                        "key": "route",
                        "cases": {"refund": "refund", "deny": "deny"},
                        "default": "deny",
                    }
                },
                "refund": {"set": {"decision": "refund"}, "next": None},
                "deny": {"set": {"decision": "deny"}, "next": None},
            },
        }
    )
    store = JSONLStore(tmp_path)
    result = Runner(wf, store).run(inputs={"ticket": "where is my order?", "route": "refund"})
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    assert any(e["type"] == "transition" for e in events)


def test_yaml_workflow_approval_resume(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "yaml-approval",
            "initial": "gate",
            "steps": {
                "gate": {
                    "approval": {
                        "id": "publish",
                        "summary": "Approve release?",
                        "on_approve": "done",
                        "on_reject": "aborted",
                    }
                },
                "done": {"set": {"status": "approved"}, "next": None},
                "aborted": {"set": {"status": "aborted"}, "next": None},
            },
        }
    )
    store = JSONLStore(tmp_path)
    paused = Runner(wf, store).run()
    assert paused.status == "paused"
    resolve_approval_on_store(store, paused.run_id, "publish", approved=True)
    resumed = Runner(wf, store).run(run_id=paused.run_id, resume=True)
    assert resumed.status == "completed"
