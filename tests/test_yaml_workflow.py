from __future__ import annotations

from pathlib import Path

import pytest

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
        }
    )

    assert wf.name == "yaml-demo"
    assert wf.initial_state == "validate"
    assert wf.transitions["validate"] == {"approved"}
    assert wf.transitions["approved"] == {"done"}
