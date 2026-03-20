from __future__ import annotations

from replayt.export_run import sanitize_event
from replayt.types import LogMode


def test_sanitize_run_started_strips_inputs() -> None:
    ev = {
        "type": "run_started",
        "payload": {"inputs": {"secret": 1}, "workflow_name": "w"},
    }
    out = sanitize_event(ev, LogMode.redacted)
    assert out["payload"]["inputs"] == {}


def test_sanitize_llm_request_redacted() -> None:
    ev = {
        "type": "llm_request",
        "payload": {"messages": [{"role": "user", "content": "x"}], "state": "s"},
    }
    out = sanitize_event(ev, LogMode.redacted)
    assert "messages" not in out["payload"]


def test_sanitize_tool_call_redacts_arguments() -> None:
    ev = {"type": "tool_call", "payload": {"name": "t", "arguments": {"a": 1}}}
    out = sanitize_event(ev, LogMode.redacted)
    assert out["payload"]["arguments"] == {"_redacted": True}
