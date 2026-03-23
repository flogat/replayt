"""Unit tests for ``replayt.cli.display`` helpers."""

from __future__ import annotations

from replayt.cli.display import (
    format_timeline_seq,
    inspect_stakeholder_markdown,
    replay_html,
    replay_timeline_lines,
    run_matches_llm_model_filter,
    run_matches_structured_schema_name_filter,
    stakeholder_report_handoff_html,
    stakeholder_report_handoff_markdown,
)


def test_stakeholder_report_handoff_includes_resume_with_approval_id() -> None:
    run_id = "rid-handoff"
    events = [
        {
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1", "tags": {}, "run_metadata": {}},
        },
        {"type": "run_paused", "payload": {"approval_id": "ship-it"}},
        {
            "type": "approval_requested",
            "payload": {"approval_id": "ship-it", "state": "review", "summary": "ok?", "details": {}},
        },
    ]
    md = stakeholder_report_handoff_markdown(run_id, events)
    assert "## Stakeholder CLI handoff" in md
    assert f"replayt bundle-export {run_id}" in md
    assert f"{run_id}-stakeholder-bundle.tar.gz" in md
    assert f"replayt resume TARGET {run_id} --approval ship-it" in md
    html = stakeholder_report_handoff_html(run_id, events)
    assert "Stakeholder CLI handoff" in html
    assert f"replayt bundle-export {run_id}" in html
    assert f"replayt resume TARGET {run_id} --approval ship-it" in html


def test_stakeholder_report_handoff_failed_includes_inspect_json() -> None:
    run_id = "rid-fail"
    events = [
        {
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1", "tags": {}, "run_metadata": {}},
        },
        {
            "type": "run_failed",
            "payload": {"state": "s", "error": {"type": "E", "message": "x"}},
        },
        {"type": "run_completed", "payload": {"status": "failed"}},
    ]
    md = stakeholder_report_handoff_markdown(run_id, events)
    assert f"replayt inspect {run_id} --output json" in md


def test_inspect_stakeholder_markdown_paused_without_pending_includes_run_id_in_inspect_hint() -> None:
    """Regression: second line of resume hint must interpolate ``run_id`` (not literal ``{run_id}``)."""

    run_id = "00000000-0000-0000-0000-00000000c0de"
    events = [
        {
            "type": "run_started",
            "payload": {
                "workflow_name": "wf",
                "workflow_version": "1",
                "tags": {},
                "run_metadata": {},
                "runtime": {"workflow": {}},
            },
        },
        {"type": "run_paused", "payload": {"reason": "operator hold"}},
    ]
    md = inspect_stakeholder_markdown(run_id, events)
    assert f"`replayt inspect {run_id} --output json`" in md
    assert "{run_id}" not in md


def test_format_timeline_seq() -> None:
    assert format_timeline_seq(0) == "0000"
    assert format_timeline_seq(12) == "0012"
    assert format_timeline_seq("7") == "0007"
    assert format_timeline_seq(None) == "----"
    assert format_timeline_seq("x") == "x"
    assert format_timeline_seq(-1) == "-1"


def test_replay_timeline_lines_missing_seq_does_not_crash() -> None:
    lines = replay_timeline_lines([{"type": "run_started", "payload": {}}])
    assert lines == ["----  run_started"]


def test_replay_timeline_lines_missing_type_uses_unknown_label() -> None:
    lines = replay_timeline_lines([{"payload": {}}])
    assert lines == ["----  unknown"]


def test_replay_timeline_lines_non_string_type_does_not_crash() -> None:
    events = [{"seq": 0, "type": ["not", "a", "string"], "payload": {"x": 1}}]
    lines = replay_timeline_lines(events)
    assert len(lines) == 1
    assert "['not', 'a', 'string']" in lines[0]
    assert "payload" not in lines[0] or "x" not in lines[0]


def test_structured_schema_filter_non_string_event_type_no_crash() -> None:
    events = [{"type": [], "payload": {"schema_name": "S"}}]
    assert not run_matches_structured_schema_name_filter(events, frozenset({"S"}))


def test_llm_model_filter_non_string_event_type_no_crash() -> None:
    events = [{"type": {}, "payload": {"effective": {"model": "m1"}}}]
    assert not run_matches_llm_model_filter(events, frozenset({"m1"}))


def test_replay_timeline_lines_stakeholder_skips_llm_and_tool_rows() -> None:
    events = [
        {"seq": 1, "type": "run_started", "payload": {}},
        {"seq": 2, "type": "llm_request", "payload": {"model": "x"}},
        {"seq": 3, "type": "tool_call", "payload": {"name": "n"}},
        {"seq": 4, "type": "state_entered", "payload": {"state": "s"}},
        {"seq": 5, "type": "run_completed", "payload": {"status": "completed"}},
    ]
    default_lines = replay_timeline_lines(events, style="default")
    assert any("llm_request" in ln for ln in default_lines)
    stake_lines = replay_timeline_lines(events, style="stakeholder")
    assert not any("llm_request" in ln for ln in stake_lines)
    assert not any("tool_call" in ln for ln in stake_lines)
    assert any("state_entered" in ln for ln in stake_lines)


def test_replay_html_stakeholder_attention_and_no_tool_call_in_body() -> None:
    events = [
        {
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {"seq": 2, "type": "tool_call", "payload": {"name": "n"}},
        {
            "seq": 3,
            "type": "run_failed",
            "payload": {"state": "s", "error": {"type": "E", "message": "boom"}},
        },
        {"seq": 4, "type": "run_completed", "payload": {"status": "failed"}},
    ]
    doc = replay_html("run-z", events, style="stakeholder")
    assert "attention=" in doc
    assert "boom" in doc
    assert "0002  tool_call" not in doc
    assert "Run timeline" in doc
