from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from replayt.exceptions import RunFailed
from replayt.llm import LLMSettings
from replayt.persistence import JSONLStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.testing import MockLLMClient
from replayt.types import LogMode, RetryPolicy
from replayt.workflow import Workflow
from replayt.yaml_workflow import workflow_from_spec


def _sha256_json(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_workflow_llm_defaults_http_retries_merge_into_effective(tmp_path: Path) -> None:
    wf = Workflow("ld", llm_defaults={"http_retries": 2})
    wf.set_initial("s")

    @wf.step("s")
    def s(ctx):
        ctx.llm.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)
        return None

    store = JSONLStore(tmp_path)
    client = MockLLMClient()
    client.enqueue("ok")
    r = Runner(wf, store, log_mode=LogMode.redacted, llm_client=client)
    res = r.run()
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    req = next(e for e in ev if e["type"] == "llm_request")
    assert req["payload"]["effective"]["http_retries"] == 2


def test_workflow_llm_defaults_merge_into_effective(tmp_path: Path) -> None:
    wf = Workflow("ld", llm_defaults={"experiment": {"cohort": "unit"}})
    wf.set_initial("s")

    @wf.step("s")
    def s(ctx):
        ctx.llm.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)
        return None

    store = JSONLStore(tmp_path)
    client = MockLLMClient()
    client.enqueue("ok")
    r = Runner(wf, store, log_mode=LogMode.redacted, llm_client=client)
    res = r.run()
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    req = next(e for e in ev if e["type"] == "llm_request")
    assert req["payload"]["effective"]["experiment"] == {"cohort": "unit"}


def test_llm_defaults_in_meta_omitted_from_workflow_meta(tmp_path: Path) -> None:
    wf = Workflow("m", meta={"llm_defaults": {"experiment": {"x": 1}}, "visible": True})
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    r.run()
    ev = store.load_events(r.run_id)
    started = next(e for e in ev if e["type"] == "run_started")
    wm = started["payload"].get("workflow_meta") or {}
    assert "llm_defaults" not in wm
    assert wm.get("visible") is True


def test_runner_run_experiment_merged_into_effective(tmp_path: Path) -> None:
    wf = Workflow("exp_wf")
    wf.set_initial("s")

    @wf.step("s")
    def s(ctx):
        ctx.llm.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)
        return None

    store = JSONLStore(tmp_path)
    client = MockLLMClient()
    client.enqueue("ok")
    r = Runner(wf, store, log_mode=LogMode.redacted, llm_client=client)
    res = r.run(experiment={"ab": "v2"})
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    started = next(e for e in ev if e["type"] == "run_started")
    assert started["payload"]["experiment"] == {"ab": "v2"}
    req = next(e for e in ev if e["type"] == "llm_request")
    assert req["payload"]["effective"]["experiment"] == {"ab": "v2"}


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


def test_runner_before_step_hook_failure_emits_terminal_events(tmp_path: Path) -> None:
    wf = Workflow("hook_fail_before")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    def before(ctx, st: str) -> None:
        raise ValueError("hook blew up")

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted, before_step=before).run()
    assert result.status == "failed"
    assert result.error == "hook blew up"
    events = store.load_events(result.run_id)
    failed = next(e for e in events if e["type"] == "run_failed")
    completed = next(e for e in events if e["type"] == "run_completed")
    assert failed["payload"]["error"]["type"] == "ValueError"
    assert completed["payload"]["status"] == "failed"
    step_errors = [e for e in events if e["type"] == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["state"] == "a"


def test_runner_after_step_hook_failure_emits_terminal_events(tmp_path: Path) -> None:
    wf = Workflow("hook_fail_after")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    def after(ctx, st: str, nxt: str | None) -> None:
        raise ValueError("hook blew up")

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted, after_step=after).run()
    assert result.status == "failed"
    assert result.error == "hook blew up"
    events = store.load_events(result.run_id)
    failed = next(e for e in events if e["type"] == "run_failed")
    completed = next(e for e in events if e["type"] == "run_completed")
    assert failed["payload"]["error"]["type"] == "ValueError"
    assert completed["payload"]["status"] == "failed"
    step_errors = [e for e in events if e["type"] == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["state"] == "a"


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


def test_workflow_contract_describes_steps_edges_and_expectations() -> None:
    wf = Workflow("contract_demo", version="7", meta={"pkg": "demo", "llm_defaults": {"experiment": {"lane": "a"}}})
    wf.set_initial("start")
    wf.note_transition("start", "done")

    @wf.step("start", retries=RetryPolicy(max_attempts=5, backoff_seconds=1.5), expects={"account_id": str})
    def start(ctx) -> str:
        return "done"

    @wf.step("done")
    def done(ctx) -> None:
        return None

    contract = wf.contract()
    assert contract["schema"] == "replayt.workflow_contract.v1"
    assert contract["contract_sha256"] == wf.contract_digest()
    assert len(contract["contract_sha256"]) == 64
    assert contract["workflow"]["name"] == "contract_demo"
    assert contract["workflow"]["llm_defaults_keys"] == ["experiment"]
    assert contract["declared_edges"] == [{"from_state": "start", "to_state": "done"}]
    start_step = next(step for step in contract["steps"] if step["name"] == "start")
    assert start_step["expects"] == [{"key": "account_id", "type": "str"}]
    assert start_step["retry_policy"] == {"max_attempts": 5, "backoff_seconds": 1.5}
    assert start_step["outgoing_transitions"] == ["done"]


def test_runner_run_started_includes_runtime_snapshot(tmp_path: Path) -> None:
    wf = Workflow("runtime_meta")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    settings = LLMSettings(
        api_key="secret",
        provider="openai",
        base_url="https://gateway.example/v1",
        model="demo-model",
        top_p=0.4,
        frequency_penalty=0.1,
        presence_penalty=-0.2,
        seed=7,
        http_retries=2,
        extra_body={"reasoning": {"effort": "high"}},
    )
    store = JSONLStore(tmp_path)
    runner = Runner(wf, store, log_mode=LogMode.full, llm_client=MockLLMClient(settings=settings), max_steps=9)
    result = runner.run()
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    started = next(e for e in events if e["type"] == "run_started")
    runtime = started["payload"]["runtime"]
    assert runtime["engine"] == {"log_mode": "full", "max_steps": 9, "redact_keys": []}
    assert runtime["store"]["class"] == "JSONLStore"
    assert runtime["hooks"] == {"before_step": False, "after_step": False}
    assert runtime["workflow"] == {
        "contract_schema": "replayt.workflow_contract.v1",
        "contract_sha256": wf.contract_digest(),
    }
    assert "policy_hooks" not in runtime
    assert runtime["llm"]["provider"] == "openai"
    assert runtime["llm"]["base_url"] == "https://gateway.example/v1"
    assert runtime["llm"]["model"] == "demo-model"
    assert runtime["llm"]["top_p"] == 0.4
    assert runtime["llm"]["frequency_penalty"] == 0.1
    assert runtime["llm"]["presence_penalty"] == -0.2
    assert runtime["llm"]["seed"] == 7
    assert runtime["llm"]["stop"] is None
    assert runtime["llm"]["extra_body_keys"] == ["reasoning"]
    assert runtime["llm"]["http_retries"] == 2
    assert runtime["llm"]["api_key_present"] is True
    assert runtime["trust_boundary"]["warnings"] == ["full log mode stores raw LLM request and response bodies on disk"]


def test_runner_runtime_and_llm_effective_sanitize_base_url(tmp_path: Path) -> None:
    wf = Workflow("runtime_redaction")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        ctx.llm.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)
        return None

    settings = LLMSettings(
        api_key="secret",
        provider="openai",
        base_url="https://user:secret@gateway.example/v1?api_key=secret",
        model="demo-model",
    )
    client = MockLLMClient(settings=settings)
    client.enqueue("ok")
    store = JSONLStore(tmp_path)

    result = Runner(wf, store, log_mode=LogMode.redacted, llm_client=client).run()

    assert result.status == "completed"
    events = store.load_events(result.run_id)
    started = next(e for e in events if e["type"] == "run_started")
    request = next(e for e in events if e["type"] == "llm_request")
    assert started["payload"]["runtime"]["llm"]["base_url"] == "https://gateway.example/v1"
    assert request["payload"]["effective"]["base_url"] == "https://gateway.example/v1"


def test_runner_persists_llm_request_schema_fingerprints(tmp_path: Path) -> None:
    class Decision(BaseModel):
        value: int

    wf = Workflow("fingerprints")
    wf.set_initial("parse")

    @wf.step("parse")
    def parse(ctx) -> None:
        ctx.llm.parse(Decision, messages=[{"role": "user", "content": "Return JSON."}])
        return None

    client = MockLLMClient()
    client.enqueue('{"value": 7}')
    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.full, llm_client=client).run()

    assert result.status == "completed"
    events = store.load_events(result.run_id)
    request = next(e["payload"] for e in events if e["type"] == "llm_request")
    response = next(e["payload"] for e in events if e["type"] == "llm_response")
    structured = next(e["payload"] for e in events if e["type"] == "structured_output")
    assert request["schema_name"] == "Decision"
    assert response["schema_name"] == "Decision"
    assert request["messages_sha256"] == _sha256_json(request["messages"])
    assert request["effective_sha256"] == _sha256_json(request["effective"])
    assert request["schema_sha256"] == _sha256_json(Decision.model_json_schema())
    assert response["messages_sha256"] == request["messages_sha256"]
    assert response["effective_sha256"] == request["effective_sha256"]
    assert response["schema_sha256"] == request["schema_sha256"]
    assert structured["messages_sha256"] == request["messages_sha256"]
    assert structured["effective_sha256"] == request["effective_sha256"]
    assert structured["schema_sha256"] == request["schema_sha256"]
    assert structured["effective"] == request["effective"]
    assert structured["usage"] == response["usage"]
    assert structured["latency_ms"] == response["latency_ms"]
    assert structured["finish_reason"] == response["finish_reason"]
    assert response["http_attempts"] == 1
    assert response["http_status"] == 200
    assert structured["http_attempts"] == response["http_attempts"]
    assert structured["http_status"] == response["http_status"]


def test_runner_run_started_includes_policy_hook_breadcrumbs(tmp_path: Path) -> None:
    wf = Workflow("runtime_policy")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    store = JSONLStore(tmp_path)
    runner = Runner(
        wf,
        store,
        log_mode=LogMode.redacted,
        policy_hooks={
            "run": {"source": "project_config:run_hook", "argv0": "python.exe", "arg_count": 3},
            "resume": {"source": "env:REPLAYT_RESUME_HOOK", "argv0": "gate.ps1", "arg_count": 2},
        },
    )
    result = runner.run()
    assert result.status == "completed"
    events = store.load_events(result.run_id)
    started = next(e for e in events if e["type"] == "run_started")
    assert started["payload"]["runtime"]["policy_hooks"] == {
        "run": {"source": "project_config:run_hook", "argv0": "python.exe", "arg_count": 3},
        "resume": {"source": "env:REPLAYT_RESUME_HOOK", "argv0": "gate.ps1", "arg_count": 2},
    }


def test_runner_redact_keys_scrub_structured_payloads(tmp_path: Path) -> None:
    class Decision(BaseModel):
        email: str
        note: str

    wf = Workflow("redact_keys")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        @ctx.tools.register
        def echo(payload):
            return {"email": payload["email"], "note": payload["note"]}

        ctx.tools.call("echo", {"payload": {"email": "tool@example.com", "note": "ok"}})
        parsed = ctx.llm.parse(
            Decision,
            messages=[{"role": "user", "content": "Return JSON with email and note."}],
        )
        ctx.set("email", "snapshot@example.com")
        ctx.set("decision", parsed.model_dump())
        ctx.request_approval("ship", summary="Ship it?", details={"email": "approval@example.com", "ticket": "T-1"})

    store = JSONLStore(tmp_path)
    client = MockLLMClient()
    client.enqueue('{"email":"model@example.com","note":"approved"}')
    result = Runner(wf, store, log_mode=LogMode.redacted, llm_client=client, redact_keys=["email"]).run(
        inputs={"email": "input@example.com", "ticket": "T-1"}
    )

    assert result.status == "paused"
    events = store.load_events(result.run_id)
    started = next(e for e in events if e["type"] == "run_started")
    tool_call = next(e for e in events if e["type"] == "tool_call")
    tool_result = next(e for e in events if e["type"] == "tool_result")
    structured = next(e for e in events if e["type"] == "structured_output")
    approval = next(e for e in events if e["type"] == "approval_requested")
    snapshot = next(e for e in events if e["type"] == "context_snapshot")

    assert started["payload"]["inputs"]["email"] == {"_redacted": True}
    assert started["payload"]["runtime"]["engine"]["redact_keys"] == ["email"]
    assert tool_call["payload"]["arguments"]["payload"]["email"] == {"_redacted": True}
    assert tool_result["payload"]["result"]["email"] == {"_redacted": True}
    assert structured["payload"]["data"]["email"] == {"_redacted": True}
    assert approval["payload"]["details"]["email"] == {"_redacted": True}
    assert snapshot["payload"]["data"]["email"] == {"_redacted": True}


def test_run_context_note_emits_step_note_event(tmp_path: Path) -> None:
    wf = Workflow("notes")
    wf.set_initial("compose")

    @wf.step("compose")
    def compose(ctx) -> None:
        ctx.note(
            "framework_summary",
            summary="langgraph sandbox completed",
            data={"nodes": 3, "tool_calls": 1},
        )
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "completed"

    events = store.load_events(result.run_id)
    note = next(e for e in events if e["type"] == "step_note")
    assert note["payload"] == {
        "state": "compose",
        "kind": "framework_summary",
        "summary": "langgraph sandbox completed",
        "data": {"nodes": 3, "tool_calls": 1},
    }


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


def test_resolve_approval_requires_actor_keys_when_configured(tmp_path: Path) -> None:
    wf = Workflow("ap_actor")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.request_approval("go", summary="proceed?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"

    with pytest.raises(ValueError, match="missing required keys: ticket_id"):
        resolve_approval_on_store(
            store,
            paused.run_id,
            "go",
            approved=True,
            actor={"email": "a@example.com"},
            required_actor_keys=["email", "ticket_id"],
        )


def test_resolve_approval_requires_reason_when_configured(tmp_path: Path) -> None:
    wf = Workflow("ap_reason")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.request_approval("go", summary="proceed?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> None:
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"

    with pytest.raises(ValueError, match="approval reason is required"):
        resolve_approval_on_store(
            store,
            paused.run_id,
            "go",
            approved=True,
            require_reason=True,
        )

    resolve_approval_on_store(
        store,
        paused.run_id,
        "go",
        approved=True,
        reason="Approved after peer review",
        require_reason=True,
    )
    resolved = [e for e in store.load_events(paused.run_id) if e["type"] == "approval_resolved"][-1]
    assert resolved["payload"]["reason"] == "Approved after peer review"


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


def test_runner_rejects_non_positive_max_steps(tmp_path: Path) -> None:
    wf = Workflow("ms")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> None:
        return None

    store = JSONLStore(tmp_path)
    with pytest.raises(ValueError, match="max_steps must be >= 1"):
        Runner(wf, store, max_steps=0)


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
    events = store.load_events(result.run_id)
    step_errors = [e for e in events if e["type"] == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["state"] == "spin"
    assert step_errors[0]["payload"]["error"]["type"] == "RunFailed"


def test_step_handler_exception_emits_step_error_event(tmp_path: Path) -> None:
    wf = Workflow("handler_fail")
    wf.set_initial("boom")
    wf.note_transition("boom", None)

    @wf.step("boom")
    def boom(ctx) -> None:
        raise RuntimeError("step exploded")

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "failed"
    events = store.load_events(result.run_id)
    step_errors = [e for e in events if e["type"] == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["state"] == "boom"
    assert step_errors[0]["payload"]["error"]["type"] == "RuntimeError"


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


def test_resume_target_pairs_fifo_when_same_approval_id_requested_twice(tmp_path: Path) -> None:
    wf = Workflow("dup_aid")
    wf.set_initial("start")

    @wf.step("start")
    def start(ctx) -> str | None:
        return None

    events = [
        {"type": "approval_requested", "payload": {"approval_id": "x", "on_approve": "first", "state": "a"}},
        {"type": "approval_requested", "payload": {"approval_id": "x", "on_approve": "second", "state": "b"}},
        {"type": "approval_resolved", "payload": {"approval_id": "x", "approved": True}},
    ]
    r = Runner(wf, store=JSONLStore(tmp_path))
    target, _paused = r._resume_target_from_events(events)
    assert target == "first"


def test_resolve_approval_consumes_oldest_pending_when_duplicate_ids(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path)
    rid = "fifoaid"
    store.append_event(rid, ts="1", typ="run_started", payload={})
    store.append_event(
        rid, ts="2", typ="approval_requested", payload={"approval_id": "x", "on_approve": "a", "state": "s"}
    )
    store.append_event(
        rid, ts="3", typ="approval_requested", payload={"approval_id": "x", "on_approve": "b", "state": "s"}
    )
    resolve_approval_on_store(store, rid, "x", approved=True)
    events = store.load_events(rid)
    n_req = sum(1 for e in events if e["type"] == "approval_requested")
    n_res = sum(1 for e in events if e["type"] == "approval_resolved")
    assert n_req == 2
    assert n_res == 1


def test_run_failed_from_step_is_not_retried(tmp_path: Path) -> None:
    wf = Workflow("no_retry_rf")
    wf.set_initial("a")

    @wf.step("a", retries=RetryPolicy(max_attempts=5, backoff_seconds=0.0))
    def a(ctx) -> str | None:
        raise RunFailed("fatal")

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    result = r.run()
    assert result.status == "failed"
    retries = [e for e in store.load_events(result.run_id) if e["type"] == "retry_scheduled"]
    assert retries == []


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


def test_resolve_approval_on_store_accepts_int_id_and_stores_string_payload(tmp_path: Path) -> None:
    wf = Workflow("numeric_id_int_resolve")
    wf.set_initial("gate")

    @wf.step("gate")
    def gate(ctx) -> str | None:
        ctx.request_approval("99", summary="ok?", on_approve="done")

    @wf.step("done")
    def done(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    paused = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert paused.status == "paused"
    resolve_approval_on_store(store, paused.run_id, 99, approved=True)  # type: ignore[arg-type]
    ev = store.load_events(paused.run_id)
    resolved = [e for e in ev if e["type"] == "approval_resolved"][-1]
    assert resolved["payload"]["approval_id"] == "99"
    assert isinstance(resolved["payload"]["approval_id"], str)
    final = Runner(wf, store, log_mode=LogMode.redacted).run(run_id=paused.run_id, resume=True)
    assert final.status == "completed"


def test_resolve_approval_on_store_raises_when_no_pending_match(tmp_path: Path) -> None:
    wf = Workflow("no_pending")
    wf.set_initial("a")

    @wf.step("a")
    def a(ctx) -> str | None:
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert r.status == "completed"
    with pytest.raises(RuntimeError, match="No pending approval"):
        resolve_approval_on_store(store, r.run_id, "missing", approved=True)
