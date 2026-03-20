from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from replayt.persistence import JSONLStore
from replayt.testing import MockLLMClient, assert_events, run_with_mock
from replayt.types import LogMode
from replayt.workflow import Workflow


class Pick(BaseModel):
    label: str


def test_run_with_mock_llm_parse(tmp_path: Path) -> None:
    wf = Workflow("mocked", version="1")
    wf.set_initial("c")
    wf.note_transition("c", "done")

    @wf.step("c")
    def classify(ctx) -> str:
        out = ctx.llm.parse(Pick, messages=[{"role": "user", "content": "pick one"}])
        ctx.set("pick", out.model_dump())
        return "done"

    @wf.step("done")
    def done(ctx) -> None:
        return None

    mock = MockLLMClient()
    mock.enqueue('{"label": "a"}')
    store = JSONLStore(tmp_path)
    r = run_with_mock(wf, store, mock, log_mode=LogMode.redacted)
    assert r.status == "completed"
    events = assert_events(store, r.run_id, "structured_output", min_count=1)
    assert events[0].get("payload", {}).get("data") == {"label": "a"}
