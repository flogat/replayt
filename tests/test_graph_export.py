from __future__ import annotations

from replayt.graph_export import workflow_to_mermaid
from replayt.workflow import Workflow


def test_mermaid_contains_steps() -> None:
    wf = Workflow("g")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> str | None:
        return None

    wf.note_transition("a", "b")

    @wf.step("b")
    def b(ctx) -> str | None:
        return None

    m = workflow_to_mermaid(wf)
    assert "s_a" in m
    assert "s_b" in m
