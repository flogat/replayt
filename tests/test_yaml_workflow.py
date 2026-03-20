from __future__ import annotations

import json
from pathlib import Path

import pytest

from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.testing import MockLLMClient, run_with_mock
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


def test_yaml_branch_int_context_matches_string_case_keys(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "branch-int",
            "initial": "b",
            "steps": {
                "b": {
                    "branch": {
                        "key": "route",
                        "cases": {"1": "one", "2": "two"},
                        "default": "two",
                    }
                },
                "one": {"next": None},
                "two": {"next": None},
            },
        }
    )
    store = JSONLStore(tmp_path)
    result = Runner(wf, store).run(inputs={"route": 1})
    assert result.status == "completed"


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


def test_yaml_llm_schema_step(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "llm-schema",
            "initial": "classify",
            "steps": {
                "classify": {
                    "require": ["ticket"],
                    "llm": {
                        "system": "You are a classifier.",
                        "prompt": "Classify: {ticket}",
                        "schema": {
                            "category": {"type": "string"},
                            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "output_key": "classification",
                    },
                    "next": "done",
                },
                "done": {"set": {"status": "classified"}},
            },
        }
    )
    mock = MockLLMClient()
    mock.enqueue(json.dumps({"category": "billing", "priority": "high"}))
    store = JSONLStore(tmp_path)
    result = run_with_mock(wf, store, mock, inputs={"ticket": "charge me twice"})
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    structured = [e for e in events if e["type"] == "structured_output"]
    assert len(structured) == 1
    assert structured[0]["payload"]["data"] == {"category": "billing", "priority": "high"}


def test_yaml_llm_text_step(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "llm-text",
            "initial": "summarize",
            "steps": {
                "summarize": {
                    "require": ["doc"],
                    "llm": {
                        "prompt": "Summarize: {doc}",
                        "output_key": "summary",
                    },
                    "next": "done",
                },
                "done": {"set": {"status": "done"}},
            },
        }
    )
    mock = MockLLMClient()
    mock.enqueue("A short summary.")
    store = JSONLStore(tmp_path)
    result = run_with_mock(wf, store, mock, inputs={"doc": "Long document text..."})
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    llm_responses = [e for e in events if e["type"] == "llm_response"]
    assert len(llm_responses) == 1


def test_yaml_llm_prompt_interpolation(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "llm-interp",
            "initial": "greet",
            "steps": {
                "greet": {
                    "require": ["name", "topic"],
                    "llm": {
                        "prompt": "Hello {name}, let's talk about {topic}.",
                        "output_key": "greeting",
                    },
                },
            },
        }
    )
    mock = MockLLMClient()
    mock.enqueue("Hi Alice!")
    store = JSONLStore(tmp_path)
    result = run_with_mock(wf, store, mock, inputs={"name": "Alice", "topic": "testing"})
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    llm_reqs = [e for e in events if e["type"] == "llm_request"]
    assert len(llm_reqs) >= 1


def test_yaml_llm_missing_output_key_raises() -> None:
    with pytest.raises(ValueError, match="output_key"):
        workflow_from_spec(
            {
                "name": "bad",
                "initial": "step1",
                "steps": {
                    "step1": {
                        "llm": {
                            "prompt": "do stuff",
                        },
                    },
                },
            }
        )

