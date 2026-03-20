from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from replayt.persistence import JSONLStore
from replayt.runner import Runner
from replayt.types import LogMode
from replayt.workflow import Workflow


class AddPayload(BaseModel):
    a: int
    b: int


class AddOut(BaseModel):
    total: int


def test_tool_registry(tmp_path: Path) -> None:
    wf = Workflow("tools")
    wf.set_initial("main")

    def add(payload: AddPayload) -> AddOut:
        return AddOut(total=payload.a + payload.b)

    @wf.step("main")
    def main(ctx) -> str | None:
        ctx.tools.register(add)
        r = ctx.tools.call("add", {"payload": {"a": 2, "b": 3}})
        ctx.set("sum", r.total)
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    res = r.run()
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    assert any(e["type"] == "tool_result" and e["payload"].get("ok") for e in ev)
