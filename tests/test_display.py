"""Unit tests for ``replayt.cli.display`` helpers."""

from __future__ import annotations

from replayt.cli.display import format_timeline_seq, inspect_stakeholder_markdown, replay_timeline_lines


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
