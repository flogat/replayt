from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from replayt.exceptions import ApprovalPending, RunFailed
from replayt.llm import LLMBridge, LLMSettings, OpenAICompatClient
from replayt.persistence.base import EventStore
from replayt.tools import ToolRegistry
from replayt.types import LogMode
from replayt.workflow import Workflow


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunResult:
    run_id: str
    status: str  # completed | failed | paused
    final_state: str | None = None
    error: str | None = None


class RunContext:
    """Mutable per-run bag + LLM/tools facades."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner
        self.run_id = runner.run_id
        self.workflow_name = runner.workflow.name
        self.data: dict[str, Any] = {}
        self.llm = LLMBridge(
            emit=runner._emit_payload,
            client=runner._llm_client,
            log_mode=runner.log_mode,
            state_getter=lambda: runner._current_state,
        )
        self.tools = ToolRegistry(emit=runner._emit_payload, state_getter=lambda: runner._current_state)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def request_approval(self, approval_id: str, *, summary: str, details: dict[str, Any] | None = None) -> None:
        self._runner._emit_payload(
            "approval_requested",
            {
                "approval_id": approval_id,
                "state": self._runner._current_state,
                "summary": summary,
                "details": details or {},
            },
        )
        raise ApprovalPending(approval_id, summary=summary, details=details)

    def is_approved(self, approval_id: str) -> bool:
        return approval_id in self._runner._resolved_approved

    def is_rejected(self, approval_id: str) -> bool:
        return approval_id in self._runner._resolved_rejected


class Runner:
    def __init__(
        self,
        workflow: Workflow,
        store: EventStore,
        *,
        llm_settings: LLMSettings | None = None,
        log_mode: LogMode = LogMode.redacted,
    ) -> None:
        self.workflow = workflow
        self.store = store
        self.log_mode = log_mode
        self._llm_client = OpenAICompatClient(llm_settings or LLMSettings.from_env())
        self.run_id: str = ""
        self._seq = 0
        self._current_state: str | None = None
        self._resolved_approved: set[str] = set()
        self._resolved_rejected: set[str] = set()

    def _emit_payload(self, typ: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        event: dict[str, Any] = {
            "ts": _utcnow_iso(),
            "run_id": self.run_id,
            "seq": self._seq,
            "type": typ,
            "payload": payload,
        }
        self.store.append(self.run_id, event)

    def _load_approval_state_from_events(self, events: list[dict[str, Any]]) -> None:
        self._resolved_approved.clear()
        self._resolved_rejected.clear()
        for e in events:
            if e.get("type") == "approval_resolved":
                p = e.get("payload") or {}
                aid = str(p.get("approval_id"))
                if p.get("approved"):
                    self._resolved_approved.add(aid)
                else:
                    self._resolved_rejected.add(aid)

    def _replay_context_data(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for e in events:
            if e.get("type") == "context_snapshot":
                p = e.get("payload") or {}
                snap = p.get("data") or {}
                if isinstance(snap, dict):
                    data = dict(snap)
        return data

    def _last_snapshot_state(self, events: list[dict[str, Any]]) -> str | None:
        last: str | None = None
        for e in events:
            if e.get("type") == "context_snapshot":
                p = e.get("payload") or {}
                last = str(p.get("state")) if p.get("state") is not None else last
        return last

    def run(
        self,
        *,
        inputs: dict[str, Any] | None = None,
        run_id: str | None = None,
        resume: bool = False,
    ) -> RunResult:
        if not self.workflow.initial_state:
            raise RuntimeError("Workflow.initial_state is not set (call set_initial)")

        self.run_id = run_id or str(uuid.uuid4())
        if resume and not run_id:
            raise ValueError("run_id is required when resume=True")
        events = self.store.load_events(self.run_id) if resume else []
        if resume:
            if not events:
                raise RuntimeError(f"No events found for run_id={self.run_id!r}")
            self._load_approval_state_from_events(events)
            max_seq = max(int(e.get("seq", 0)) for e in events)
            self._seq = max_seq
        else:
            self._seq = 0

        start_state = self.workflow.initial_state
        ctx_data: dict[str, Any] = {}
        if resume and events:
            ctx_data = self._replay_context_data(events)
            snapped = self._last_snapshot_state(events)
            if snapped:
                start_state = snapped

        if not resume:
            self._emit_payload(
                "run_started",
                {
                    "workflow_name": self.workflow.name,
                    "workflow_version": self.workflow.version,
                    "initial_state": self.workflow.initial_state,
                    "inputs": inputs or {},
                },
            )

        ctx = RunContext(self)
        ctx.data.update(ctx_data)
        if inputs is not None and not resume:
            ctx.data.update(inputs)

        state: str | None = start_state
        try:
            while state is not None:
                self._current_state = state
                handler = self.workflow.get_handler(state)
                policy = self.workflow.retry_policy_for(state)

                self._emit_payload("state_entered", {"state": state})

                next_state: str | None = None
                last_err: Exception | None = None
                for attempt in range(1, policy.max_attempts + 1):
                    try:
                        next_state = handler(ctx)
                        if not self.workflow.allows_transition(state, next_state):
                            allowed = [dst for src, dst in self.workflow.edges() if src == state]
                            raise RuntimeError(
                                f"Step {state!r} returned undeclared transition {next_state!r}; allowed={allowed}"
                            )
                        last_err = None
                        break
                    except ApprovalPending:
                        self._emit_payload(
                            "context_snapshot",
                            {"state": state, "data": dict(ctx.data)},
                        )
                        self._emit_payload(
                            "run_paused",
                            {"reason": "approval_required"},
                        )
                        return RunResult(self.run_id, "paused", final_state=state)
                    except Exception as e:  # noqa: BLE001
                        next_state = None
                        last_err = e
                        if attempt >= policy.max_attempts:
                            break
                        self._emit_payload(
                            "retry_scheduled",
                            {
                                "state": state,
                                "attempt": attempt,
                                "max_attempts": policy.max_attempts,
                                "error": str(e),
                            },
                        )
                        if policy.backoff_seconds > 0:
                            time.sleep(policy.backoff_seconds)

                if last_err is not None and next_state is None:
                    self._emit_payload(
                        "run_failed",
                        {"error": str(last_err), "state": state},
                    )
                    raise RunFailed(str(last_err)) from last_err

                self._emit_payload(
                    "state_exited",
                    {"state": state, "next_state": next_state},
                )
                if next_state is not None and next_state != state:
                    self._emit_payload(
                        "transition",
                        {"from_state": state, "to_state": next_state, "reason": ""},
                    )

                state = next_state if next_state not in ("", None) else None

            self._emit_payload(
                "run_completed",
                {"final_state": self._current_state, "status": "completed"},
            )
            return RunResult(self.run_id, "completed", final_state=self._current_state)
        except RunFailed as e:
            self._emit_payload("run_completed", {"final_state": self._current_state, "status": "failed"})
            return RunResult(self.run_id, "failed", final_state=self._current_state, error=str(e))


def resolve_approval_on_store(store: EventStore, run_id: str, approval_id: str, *, approved: bool) -> None:
    """Append an `approval_resolved` event; resume execution via `Runner.run(..., resume=True)`."""
    events = store.load_events(run_id)
    seq = max((int(e.get("seq", 0)) for e in events), default=0)
    seq += 1
    event: dict[str, Any] = {
        "ts": _utcnow_iso(),
        "run_id": run_id,
        "seq": seq,
        "type": "approval_resolved",
        "payload": {"approval_id": approval_id, "approved": approved, "resolver": "cli"},
    }
    store.append(run_id, event)
