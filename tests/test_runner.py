from __future__ import annotations

from pathlib import Path

from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.types import LogMode, RetryPolicy
from replayt.workflow import Workflow
from replayt.yaml_workflow import workflow_from_spec


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
