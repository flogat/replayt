from __future__ import annotations

from pathlib import Path

from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.types import LogMode, RetryPolicy
from replayt.workflow import Workflow


def test_linear_run(tmp_path: Path) -> None:
    wf = Workflow("linear")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> str:
        ctx.set("x", 1)
        return "b"

    @wf.step("b")
    def b(ctx) -> str | None:
        ctx.set("y", ctx.get("x") + 1)
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    result = r.run(inputs={"seed": True})
    assert result.status == "completed"
    ev = store.load_events(result.run_id)
    assert any(e["type"] == "run_completed" for e in ev)


def test_approval_resume(tmp_path: Path) -> None:
    wf = Workflow("ap")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        if ctx.is_approved("go"):
            return None
        ctx.request_approval("go", summary="proceed?")

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    p = r.run()
    assert p.status == "paused"
    resolve_approval_on_store(store, p.run_id, "go", approved=True)
    r2 = Runner(wf, store, log_mode=LogMode.redacted)
    c = r2.run(run_id=p.run_id, resume=True)
    assert c.status == "completed"


def test_retry_then_success(tmp_path: Path) -> None:
    wf = Workflow("retry")
    wf.set_initial("flaky")

    @wf.step("flaky", retries=RetryPolicy(max_attempts=3, backoff_seconds=0.0))
    def flaky(ctx) -> str | None:
        n = int(ctx.get("n", 0))
        ctx.set("n", n + 1)
        if n < 2:
            raise RuntimeError("transient")
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    result = r.run()
    assert result.status == "completed"
    assert any(e["type"] == "retry_scheduled" for e in store.load_events(result.run_id))


def test_fail_after_retries(tmp_path: Path) -> None:
    wf = Workflow("bad")
    wf.set_initial("x")

    @wf.step("x", retries=RetryPolicy(max_attempts=2, backoff_seconds=0.0))
    def x(ctx) -> str | None:
        raise RuntimeError("nope")

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    result = r.run()
    assert result.status == "failed"
    assert result.error


def test_fails_on_undeclared_transition(tmp_path: Path) -> None:
    wf = Workflow("edges")
    wf.set_initial("start")
    wf.note_transition("start", "done")

    @wf.step("start")
    def start(ctx) -> str:
        return "surprise"

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "failed"
    assert "undeclared transition" in str(result.error)
