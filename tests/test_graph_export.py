from __future__ import annotations

from replayt.graph_export import mermaid_label, workflow_to_mermaid
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


def test_mermaid_ids_do_not_collapse_distinct_state_names() -> None:
    wf = Workflow("collide")
    wf.set_initial("a-b")
    wf.note_transition("a-b", "a_b")

    @wf.step("a-b")
    def hyphen(ctx) -> str:
        return "a_b"

    @wf.step("a_b")
    def underscore(ctx) -> None:
        return None

    m = workflow_to_mermaid(wf)
    assert '["a-b"]' in m
    assert '["a_b"]' in m
    ids = [line.split("[", 1)[0].strip() for line in m.splitlines() if '["a-' in line or '["a_' in line]
    assert len(ids) == 2
    assert ids[0] != ids[1]


def test_mermaid_label_coerces_non_string() -> None:
    assert "&lt;" not in mermaid_label(1)
    assert "1" in mermaid_label(1)


def test_mermaid_escapes_quoted_state_names() -> None:
    wf = Workflow("quotes")
    wf.set_initial('say "hi"')
    wf.note_transition('say "hi"', "done")

    @wf.step('say "hi"')
    def quoted(ctx) -> str:
        return "done"

    @wf.step("done")
    def done(ctx) -> None:
        return None

    m = workflow_to_mermaid(wf)
    assert 'entry: say &quot;hi&quot;' in m
    assert '["say &quot;hi&quot;"]' in m
