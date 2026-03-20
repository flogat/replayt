from __future__ import annotations

from pathlib import Path

import pytest

from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.types import LogMode, RetryPolicy
from replayt.workflow import Workflow
from replayt.yaml_workflow import workflow_from_spec


def test_runner_run_metadata_on_run_started(tmp_path: Path) -> None:
    wf = Workflow("meta_wf")
    wf.set_initial("s")

    @wf.step("s")
    def s(ctx):
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    res = r.run(run_metadata={"experiment": "A", "n": 1})
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    started = next(e for e in ev if e["type"] == "run_started")
    assert started["payload"]["run_metadata"] == {"experiment": "A", "n": 1}


def test_runner_before_after_step_hooks(tmp_path: Path) -> None:
    wf = Workflow("hooks_wf")
    wf.set_initial("a")
    wf.note_transition("a", "b")
    wf.note_transition("b", None)

    @wf.step("a")
    def a(ctx) -> str:
        ctx.set("seen", list(ctx.get("seen", [])) + ["handler_a"])
        return "b"

    @wf.step("b")
    def b(ctx) -> None:
        ctx.set("seen", list(ctx.get("seen", [])) + ["handler_b"])
        return None

    log: list[tuple[str, ...]] = []

    def before(ctx, st: str) -> None:
        log.append(("before", st))

    def after(ctx, st: str, nxt: str | None) -> None:
        log.append(("after", st, nxt))

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted, before_step=before, after_step=after)
    result = r.run()
    assert result.status == "completed"
    assert ("before", "a") in log
    assert ("after", "a", "b") in log
    assert ("before", "b") in log
    assert ("after", "b", None) in log
    ev = store.load_events(result.run_id)
    completed_ev = next(e for e in ev if e["type"] == "run_completed")
    assert completed_ev["payload"]["status"] == "completed"


def test_workflow_meta_in_run_started(tmp_path: Path) -> None:
    wf = Workflow("m", version="2", meta={"pkg": "demo", "git_sha": "abc"})
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    result = r.run()
    ev = store.load_events(result.run_id)
    started = next(e for e in ev if e["type"] == "run_started")
    assert started["payload"]["workflow_meta"] == {"pkg": "demo", "git_sha": "abc"}


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
        ctx.request_approval("go", summary="proceed?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        ctx.set("done", True)
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    p = r.run()
    assert p.status == "paused"
    resolve_approval_on_store(store, p.run_id, "go", approved=True)
    r2 = Runner(wf, store, log_mode=LogMode.redacted)
    c = r2.run(run_id=p.run_id, resume=True)
    assert c.status == "completed"


def test_approval_resume_skips_replaying_side_effects_with_resume_target(tmp_path: Path) -> None:
    wf = Workflow("ap_side_effect")
    wf.set_initial("gate")
    wf.note_transition("gate", "done")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.set("writes", int(ctx.get("writes", 0)) + 1)
        ctx.request_approval("go", summary="proceed?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        assert ctx.get("writes") == 1
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"
    resolve_approval_on_store(store, paused.run_id, "go", approved=True)
    completed = Runner(wf, store, log_mode=LogMode.redacted).run(run_id=paused.run_id, resume=True)
    assert completed.status == "completed"
    events = store.load_events(paused.run_id)
    gate_entries = [e for e in events if e["type"] == "state_entered" and e["payload"].get("state") == "gate"]
    assert len(gate_entries) == 1
    assert any(e["type"] == "approval_applied" for e in events)



def test_yaml_approval_resume_without_explicit_targets_completes(tmp_path: Path) -> None:
    wf = workflow_from_spec(
        {
            "name": "yaml-approval-no-target",
            "initial": "gate",
            "steps": {
                "gate": {
                    "approval": {
                        "id": "publish",
                        "summary": "Approve release?",
                    }
                },
            },
        }
    )

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"

    resolve_approval_on_store(store, paused.run_id, "publish", approved=True)

    resumed = Runner(wf, store, log_mode=LogMode.redacted).run(run_id=paused.run_id, resume=True)
    assert resumed.status == "completed"

    events = store.load_events(paused.run_id)
    approval_requests = [e for e in events if e["type"] == "approval_requested"]
    assert len(approval_requests) == 1


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
    retry_event = next(e for e in store.load_events(result.run_id) if e["type"] == "retry_scheduled")
    assert retry_event["payload"]["error"]["type"] == "RuntimeError"


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
    failed_event = next(e for e in store.load_events(result.run_id) if e["type"] == "run_failed")
    assert failed_event["payload"]["error"]["type"] == "RuntimeError"


def test_retry_policy_rejects_non_positive_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=-1)


def test_yaml_workflow_rejects_invalid_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        workflow_from_spec(
            {
                "name": "bad-retry",
                "initial": "a",
                "steps": {
                    "a": {"retry": {"max_attempts": 0}, "next": None},
                },
            }
        )


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


def test_expects_list_missing_key_fails(tmp_path: Path) -> None:
    wf = Workflow("schema")
    wf.set_initial("need_key")

    @wf.step("need_key", expects=["account_id"])
    def need_key(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "failed"
    assert "account_id" in str(result.error)


def test_expects_dict_wrong_type_fails(tmp_path: Path) -> None:
    wf = Workflow("schema_type")
    wf.set_initial("typed")

    @wf.step("typed", expects={"account_id": str})
    def typed(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"account_id": 42})
    assert result.status == "failed"
    assert "expected str" in str(result.error)
    assert "got int" in str(result.error)


def test_expects_dict_correct_type_succeeds(tmp_path: Path) -> None:
    wf = Workflow("schema_ok")
    wf.set_initial("typed")

    @wf.step("typed", expects={"account_id": str})
    def typed(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"account_id": "abc"})
    assert result.status == "completed"


def test_expects_list_validates_existence(tmp_path: Path) -> None:
    wf = Workflow("schema_list")
    wf.set_initial("check")

    @wf.step("check", expects=["x", "y"])
    def check(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"x": 1})
    assert result.status == "failed"
    assert "missing key 'y'" in str(result.error)

    result_ok = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"x": 1, "y": 2})
    assert result_ok.status == "completed"


def test_context_schema_error_message_includes_step_and_violations(tmp_path: Path) -> None:
    wf = Workflow("schema_msg")
    wf.set_initial("validate")

    @wf.step("validate", expects={"name": str, "age": int})
    def validate(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"name": 123})
    assert result.status == "failed"
    assert "validate" in str(result.error)
    assert "missing key 'age'" in str(result.error)
    assert "expected str" in str(result.error)


def test_context_schema_error_logged_as_step_error_event(tmp_path: Path) -> None:
    wf = Workflow("schema_event")
    wf.set_initial("guarded")

    @wf.step("guarded", expects=["token"])
    def guarded(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "failed"

    events = store.load_events(result.run_id)
    step_errors = [e for e in events if e["type"] == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["state"] == "guarded"
    assert step_errors[0]["payload"]["error"]["type"] == "ContextSchemaError"


def test_context_snapshot_deep_copies_nested_data(tmp_path: Path) -> None:
    """Verify that mutating nested context data after a snapshot does not corrupt the snapshot."""

    wf = Workflow("deep_copy")
    wf.set_initial("gate")
    wf.note_transition("gate", "verify")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.set("nested", {"items": [1, 2, 3]})
        if ctx.is_approved("go"):
            return "verify"
        ctx.request_approval("go", summary="proceed?", on_approve="verify")

    @wf.step("verify")
    def verify(ctx) -> str | None:
        assert ctx.get("nested") == {"items": [1, 2, 3]}, "snapshot must preserve original nested data"
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"

    resolve_approval_on_store(store, paused.run_id, "go", approved=True)
    completed = Runner(wf, store, log_mode=LogMode.redacted).run(run_id=paused.run_id, resume=True)
    assert completed.status == "completed"


def test_runner_context_manager_closes_client(tmp_path: Path) -> None:
    wf = Workflow("ctx_mgr")
    wf.set_initial("start")

    @wf.step("start")
    def start(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    with Runner(wf, store, log_mode=LogMode.redacted) as r:
        result = r.run()
    assert result.status == "completed"
    assert r._llm_client._http is None


def test_max_steps_prevents_infinite_loop(tmp_path: Path) -> None:
    wf = Workflow("loop")
    wf.set_initial("spin")

    @wf.step("spin")
    def spin(ctx) -> str:
        return "spin"

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted, max_steps=5).run()
    assert result.status == "failed"
    assert "max_steps" in str(result.error)


def test_expects_rejects_none_when_typed(tmp_path: Path) -> None:
    """Setting a key to None should fail validation when a concrete type is expected."""
    wf = Workflow("none_check")
    wf.set_initial("guarded")

    @wf.step("guarded", expects={"name": str})
    def guarded(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"name": None})
    assert result.status == "failed"
    assert "expected str" in str(result.error)
    assert "NoneType" in str(result.error)


def test_expects_allows_none_when_generic(tmp_path: Path) -> None:
    """expects=["key"] (list form) uses type=object, which should accept any value including None."""
    wf = Workflow("none_ok")
    wf.set_initial("loose")

    @wf.step("loose", expects=["name"])
    def loose(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run(inputs={"name": None})
    assert result.status == "completed"


def test_runner_reuse_does_not_leak_approval_state(tmp_path: Path) -> None:
    """H1: Approval sets from a paused run must not leak into a subsequent fresh run."""

    wf = Workflow("reuse")
    wf.set_initial("gate")
    wf.note_transition("gate", "done")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        if ctx.is_approved("go"):
            return "done"
        ctx.request_approval("go", summary="proceed?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    runner = Runner(wf, store, log_mode=LogMode.redacted)

    paused = runner.run()
    assert paused.status == "paused"

    from replayt.runner import resolve_approval_on_store

    resolve_approval_on_store(store, paused.run_id, "go", approved=True)
    resumed = runner.run(run_id=paused.run_id, resume=True)
    assert resumed.status == "completed"

    fresh = runner.run()
    assert fresh.status == "paused", "Fresh run should NOT see stale approval from previous run"


def test_runner_context_snapshot_survives_non_copyable_value(tmp_path: Path) -> None:
    """M6: Shallow-copy fallback when deepcopy fails on non-copyable context values."""

    wf = Workflow("non_copy")
    wf.set_initial("gate")

    class _NoCopy:
        def __deepcopy__(self, memo):
            raise TypeError("cannot deepcopy")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.set("widget", _NoCopy())
        ctx.request_approval("check", summary="ok?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "paused"
    events = store.load_events(result.run_id)
    assert any(e["type"] == "context_snapshot" for e in events)


def test_approval_outcomes_last_resolution_wins(tmp_path: Path) -> None:
    wf = Workflow("ap_out")
    wf.set_initial("x")

    @wf.step("x")
    def x(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    rid = "r1"
    store.append_event(rid, ts="1", typ="run_started", payload={})
    store.append_event(
        rid, ts="2", typ="approval_resolved", payload={"approval_id": "ship", "approved": True}
    )
    store.append_event(
        rid, ts="3", typ="approval_resolved", payload={"approval_id": "ship", "approved": False}
    )
    r = Runner(wf, store, log_mode=LogMode.redacted)
    r._load_approval_state_from_events(store.load_events(rid))
    assert r._approval_outcomes["ship"] is False
    from replayt.runner import RunContext

    ctx = RunContext(r)
    assert ctx.is_rejected("ship")
    assert not ctx.is_approved("ship")


def test_resume_target_prefers_latest_chronological_resolution(tmp_path: Path) -> None:
    wf = Workflow("resume_order")
    wf.set_initial("start")

    @wf.step("start")
    def start(ctx) -> str | None:
        return None

    events = [
        {"type": "approval_requested", "payload": {"approval_id": "a", "on_approve": "s1", "state": "g1"}},
        {"type": "approval_requested", "payload": {"approval_id": "b", "on_approve": "s2", "state": "g2"}},
        {"type": "approval_resolved", "payload": {"approval_id": "b", "approved": True}},
        {"type": "approval_resolved", "payload": {"approval_id": "a", "approved": True}},
    ]
    r = Runner(wf, store=JSONLStore(tmp_path))
    target, _paused = r._resume_target_from_events(events)
    assert target == "s1"


def test_resolve_approval_accepts_string_for_numeric_logged_id(tmp_path: Path) -> None:
    wf = Workflow("numeric_id")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.request_approval(123, summary="ok?", on_approve="done")  # type: ignore[arg-type]

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"
    resolve_approval_on_store(store, paused.run_id, "123", approved=True)
    final = Runner(wf, store, log_mode=LogMode.redacted).run(run_id=paused.run_id, resume=True)
    assert final.status == "completed"
