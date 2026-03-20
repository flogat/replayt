from __future__ import annotations

from pathlib import Path

from replayt.cli.config import resolve_strict_mirror
from replayt.cli.validation import validate_workflow_graph, validation_report
from replayt.workflow import Workflow


def test_multi_state_without_edges_emits_warning_not_error() -> None:
    wf = Workflow("w")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx):
        return "b"

    @wf.step("b")
    def b(ctx):
        return None

    errors, warnings = validate_workflow_graph(wf, strict_graph=False)
    assert errors == []
    assert len(warnings) == 1
    assert "no declared transitions" in warnings[0]


def test_strict_graph_no_edges_is_error() -> None:
    wf = Workflow("w")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx):
        return "b"

    @wf.step("b")
    def b(ctx):
        return None

    errors, warnings = validate_workflow_graph(wf, strict_graph=True)
    assert errors
    assert warnings == []


def test_validation_report_includes_warnings_key() -> None:
    wf = Workflow("solo")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx):
        return None

    errors, warnings = validate_workflow_graph(wf, strict_graph=False)
    report = validation_report(
        target="t",
        wf=wf,
        strict_graph=False,
        errors=errors,
        warnings=warnings,
        inputs_json=None,
        metadata_json=None,
        experiment_json=None,
    )
    assert report["warnings"] == []
    assert "warnings" in report


def test_resolve_strict_mirror_defaults() -> None:
    assert resolve_strict_mirror({}, sqlite=Path("x.db")) is True
    assert resolve_strict_mirror({}, sqlite=None) is False
    assert resolve_strict_mirror({"strict_mirror": False}, sqlite=Path("x.db")) is False
    assert resolve_strict_mirror({"strict_mirror": True}, sqlite=None) is True
