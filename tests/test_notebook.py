from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from replayt.notebook import _build_mermaid_source, display_graph, display_run
from replayt.runner import RunResult
from replayt.workflow import Workflow


class _FakeHTML:
    """Mimics IPython.display.HTML enough for testing."""

    def __init__(self, data: str = "") -> None:
        self.data = data


def _make_workflow() -> Workflow:
    wf = Workflow("demo")
    wf.set_initial("start")

    @wf.step("start")
    def start(ctx: Any) -> str:
        return "end"

    @wf.step("end")
    def end(ctx: Any) -> None:
        return None

    wf.note_transition("start", "end")
    return wf


class TestDisplayGraph:
    def test_mermaid_source_contains_steps_and_edges(self) -> None:
        wf = _make_workflow()
        src = _build_mermaid_source(wf)
        assert "graph TD" in src
        assert "start" in src
        assert "end" in src
        assert "start --> end" in src

    def test_initial_state_labelled(self) -> None:
        wf = _make_workflow()
        src = _build_mermaid_source(wf)
        assert "(start)" in src

    def test_fallback_prints_text_when_no_ipython(self, capsys: Any) -> None:
        wf = _make_workflow()
        with patch("replayt.notebook._HAS_IPYTHON", False):
            result = display_graph(wf)
        assert result is None
        captured = capsys.readouterr()
        assert "graph TD" in captured.out

    def test_returns_html_when_ipython_available(self) -> None:
        wf = _make_workflow()
        mock_display = MagicMock()
        with (
            patch("replayt.notebook._HAS_IPYTHON", True),
            patch("replayt.notebook._IPyHTML", _FakeHTML),
            patch("replayt.notebook._ipython_display", mock_display),
        ):
            obj = display_graph(wf)
        assert obj is not None
        assert "mermaid" in obj.data


class _FakeStore:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._events)


class TestDisplayRun:
    def test_renders_timeline_html(self) -> None:
        events = [
            {"type": "run_started", "ts": "2025-01-01T00:00:00Z", "payload": {"workflow_name": "demo", "inputs": {}}},
            {"type": "state_entered", "ts": "2025-01-01T00:00:01Z", "payload": {"state": "start"}},
            {
                "type": "structured_output",
                "ts": "2025-01-01T00:00:02Z",
                "payload": {"value": 42},
            },
            {
                "type": "tool_call",
                "ts": "2025-01-01T00:00:03Z",
                "payload": {"name": "calc", "arguments": {"x": 1}},
            },
            {
                "type": "tool_result",
                "ts": "2025-01-01T00:00:04Z",
                "payload": {"result": 2},
            },
            {
                "type": "run_completed",
                "ts": "2025-01-01T00:00:05Z",
                "payload": {"status": "completed", "final_state": "end"},
            },
        ]
        store = _FakeStore(events)
        mock_display = MagicMock()
        with (
            patch("replayt.notebook._HAS_IPYTHON", True),
            patch("replayt.notebook._IPyHTML", _FakeHTML),
            patch("replayt.notebook._ipython_display", mock_display),
        ):
            obj = display_run(store, "run-123")
        assert obj is not None
        html_out = obj.data
        assert "run-123" in html_out
        assert "run_started" in html_out
        assert "state_entered" in html_out
        assert "run_completed" in html_out
        assert "tailwindcss" in html_out

    def test_fallback_prints_when_no_ipython(self, capsys: Any) -> None:
        store = _FakeStore([{"type": "run_started", "ts": "t0", "payload": {"workflow_name": "w"}}])
        with patch("replayt.notebook._HAS_IPYTHON", False):
            result = display_run(store, "r1")
        assert result is None
        captured = capsys.readouterr()
        assert "r1" in captured.out

    def test_handles_run_failed_event(self) -> None:
        events = [
            {
                "type": "run_failed",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"error": {"message": "boom"}, "state": "start"},
            },
        ]
        store = _FakeStore(events)
        mock_display = MagicMock()
        with (
            patch("replayt.notebook._HAS_IPYTHON", True),
            patch("replayt.notebook._IPyHTML", _FakeHTML),
            patch("replayt.notebook._ipython_display", mock_display),
        ):
            obj = display_run(store, "run-fail")
        assert "boom" in obj.data


class TestRunResultReprHtml:
    def test_completed_status(self) -> None:
        r = RunResult(run_id="r1", status="completed", final_state="done")
        html_out = r._repr_html_()
        assert "r1" in html_out
        assert "completed" in html_out
        assert "done" in html_out
        assert "#d1fae5" in html_out

    def test_failed_status_shows_error(self) -> None:
        r = RunResult(run_id="r2", status="failed", final_state="broken", error="something broke")
        html_out = r._repr_html_()
        assert "failed" in html_out
        assert "#fee2e2" in html_out
        assert "something broke" in html_out

    def test_paused_status(self) -> None:
        r = RunResult(run_id="r3", status="paused", final_state="gate")
        html_out = r._repr_html_()
        assert "paused" in html_out
        assert "#fef9c3" in html_out

    def test_unknown_status_uses_gray(self) -> None:
        r = RunResult(run_id="r4", status="weird")
        html_out = r._repr_html_()
        assert "#f3f4f6" in html_out

    def test_no_error_field_when_absent(self) -> None:
        r = RunResult(run_id="r5", status="completed", final_state="end")
        html_out = r._repr_html_()
        assert "error:" not in html_out
