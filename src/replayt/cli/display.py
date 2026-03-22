"""Event summaries, replay HTML/text, filters, and time parsing for CLI commands."""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

import typer

REPLAY_HTML_CSS = """
body{background:#f8fafc;color:#0f172a;font-family:ui-sans-serif,system-ui,sans-serif;margin:0;padding:24px}
main{max-width:56rem;margin:0 auto}
.title{font-size:1.5rem;font-weight:600;margin:0 0 .5rem}
.sub{font-size:.875rem;color:#475569;margin:0 0 1rem}
.card{
  background:#fff;
  border:1px solid #e2e8f0;
  border-radius:.5rem;
  box-shadow:0 1px 2px rgba(15,23,42,.08);
  padding:1rem
}
.row{
  font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:.875rem;
  white-space:pre-wrap;
  border-bottom:1px solid #e2e8f0;
  padding:.25rem 0
}
.foot{font-size:.75rem;color:#64748b;margin-top:1rem}
"""


def event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "unknown",
        "workflow_name": None,
        "workflow_version": None,
        "workflow_contract_sha256": None,
        "state_count": 0,
        "transition_count": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "notes": 0,
        "approvals": 0,
        "last_ts": None,
        "tags": {},
        "run_metadata": {},
        "experiment": {},
    }
    for event in events:
        summary["last_ts"] = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}
        if typ == "run_started":
            summary["workflow_name"] = payload.get("workflow_name")
            summary["workflow_version"] = payload.get("workflow_version")
            summary["tags"] = payload.get("tags") or {}
            summary["run_metadata"] = payload.get("run_metadata") or {}
            runtime = payload.get("runtime") or {}
            workflow_runtime = runtime.get("workflow") if isinstance(runtime, dict) else {}
            if isinstance(workflow_runtime, dict):
                digest = workflow_runtime.get("contract_sha256")
                if isinstance(digest, str) and digest:
                    summary["workflow_contract_sha256"] = digest
            exp = payload.get("experiment")
            summary["experiment"] = exp if isinstance(exp, dict) else {}
        elif typ == "state_entered":
            summary["state_count"] += 1
        elif typ == "transition":
            summary["transition_count"] += 1
        elif typ == "llm_request":
            summary["llm_calls"] += 1
        elif typ == "tool_call":
            summary["tool_calls"] += 1
        elif typ == "step_note":
            summary["notes"] += 1
        elif typ == "approval_requested":
            summary["approvals"] += 1
        elif typ == "run_completed":
            summary["status"] = payload.get("status", summary["status"])
        elif typ == "run_paused":
            summary["status"] = "paused"
    return summary


def _inline_error_message(error: Any) -> str:
    if isinstance(error, dict):
        err_type = str(error.get("type") or "").strip()
        err_message = str(error.get("message") or "").strip()
        if err_type and err_message:
            return f"{err_type}: {err_message}"
        return err_type or err_message
    if error is None:
        return ""
    return str(error).strip()


def _truncate_inline(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def run_attention_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the current stakeholder-facing action on a run for ``replayt runs``."""

    summary = event_summary(events)
    approvals: list[dict[str, Any]] = []
    pending_by_id: dict[str, deque[int]] = defaultdict(deque)
    latest_failure: dict[str, Any] | None = None
    latest_structured_output_failure: dict[str, Any] | None = None
    latest_run_paused: dict[str, Any] | None = None

    for event in events:
        ts = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}

        if typ == "approval_requested":
            approval_id = payload.get("approval_id")
            if approval_id is None:
                continue
            approvals.append(
                {
                    "approval_id": str(approval_id),
                    "state": payload.get("state"),
                    "summary": payload.get("summary"),
                    "requested_ts": ts,
                    "approved": None,
                }
            )
            pending_by_id[str(approval_id)].append(len(approvals) - 1)
        elif typ == "approval_resolved":
            approval_id = payload.get("approval_id")
            if approval_id is None:
                continue
            pending = pending_by_id.get(str(approval_id))
            if pending:
                approvals[pending.popleft()]["approved"] = bool(payload.get("approved"))
        elif typ == "run_failed":
            latest_failure = {
                "state": payload.get("state"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "structured_output_failed":
            latest_structured_output_failure = {
                "state": payload.get("state"),
                "schema_name": payload.get("schema_name"),
                "stage": payload.get("stage"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "run_paused":
            latest_run_paused = {
                "approval_id": payload.get("approval_id"),
                "reason": payload.get("reason"),
                "ts": ts,
            }

    pending_approvals = [
        {
            "approval_id": approval.get("approval_id"),
            "state": approval.get("state"),
            "summary": approval.get("summary"),
            "requested_ts": approval.get("requested_ts"),
        }
        for approval in approvals
        if approval.get("approved") is None
    ]
    if not pending_approvals and summary.get("status") == "paused" and latest_run_paused is not None:
        paused_approval_id = latest_run_paused.get("approval_id")
        if paused_approval_id not in (None, ""):
            pending_approvals.append(
                {
                    "approval_id": str(paused_approval_id),
                    "state": None,
                    "summary": None,
                    "requested_ts": latest_run_paused.get("ts"),
                }
            )

    attention_kind = "none"
    attention_summary = ""
    status = str(summary.get("status") or "unknown")
    if status == "paused":
        attention_kind = "pending_approval"
        if len(pending_approvals) == 1:
            approval = pending_approvals[0]
            attention_summary = f"awaiting approval {approval.get('approval_id') or 'approval'}"
            state = approval.get("state")
            if state not in (None, ""):
                attention_summary += f" @ {state}"
        elif len(pending_approvals) > 1:
            attention_summary = f"awaiting {len(pending_approvals)} approvals"
        else:
            pause_reason = str(latest_run_paused.get("reason") or "").strip() if latest_run_paused else ""
            attention_summary = f"paused: {pause_reason}" if pause_reason else "paused"
    elif status == "failed":
        if latest_failure is not None:
            attention_kind = "run_failed"
            state = str(latest_failure.get("state") or "").strip()
            err = _inline_error_message(latest_failure.get("error"))
            if state and err:
                attention_summary = f"failed in {state}: {err}"
            elif state:
                attention_summary = f"failed in {state}"
            elif err:
                attention_summary = f"failed: {err}"
            else:
                attention_summary = "failed"
        elif latest_structured_output_failure is not None:
            attention_kind = "structured_output_failed"
            schema_name = str(latest_structured_output_failure.get("schema_name") or "").strip()
            stage = str(latest_structured_output_failure.get("stage") or "").strip()
            if schema_name and stage:
                attention_summary = f"parse failure {schema_name} ({stage})"
            elif schema_name:
                attention_summary = f"parse failure {schema_name}"
            else:
                attention_summary = "failed"

    return {
        "attention_kind": attention_kind,
        "attention_summary": _truncate_inline(attention_summary) if attention_summary else "",
        "pending_approvals": pending_approvals,
        "latest_failure": latest_failure,
        "latest_structured_output_failure": latest_structured_output_failure,
    }


def replay_timeline_lines(events: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for e in events:
        typ = e.get("type")
        seq = e.get("seq")
        payload = e.get("payload") or {}
        line = f"{seq:04d}  {typ}"
        if typ in {
            "state_entered",
            "state_exited",
            "transition",
            "run_failed",
            "approval_requested",
            "structured_output",
            "step_note",
            "tool_call",
            "tool_result",
        }:
            raw = json.dumps(payload, ensure_ascii=False, default=str)
            if len(raw) > 500:
                raw = raw[:497] + "..."
            line += f"  {raw}"
        lines.append(line)
    return lines


def replay_html(run_id: str, events: list[dict[str, Any]]) -> str:
    summary = event_summary(events)
    title = html.escape(f"replayt run {run_id}")
    rows = []
    pre = '<pre class="row">'
    for line in replay_timeline_lines(events):
        rows.append(f"{pre}{html.escape(line)}</pre>")
    body_rows = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <style>{REPLAY_HTML_CSS}</style>
</head>
<body>
  <main>
    <h1 class="title">{title}</h1>
    <p class="sub">
      status={html.escape(str(summary.get("status")))}
      workflow={html.escape(str(summary.get("workflow_name")))}@{html.escape(str(summary.get("workflow_version")))}
    </p>
    <section class="card">
      {body_rows}
    </section>
    <p class="foot">Generated by replayt (no model calls; timeline from local event store).</p>
  </main>
</body>
</html>
"""


def parse_tag_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"Tag filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def tags_match(run_tags: dict[str, str], filters: dict[str, str]) -> bool:
    return all(run_tags.get(k) == v for k, v in filters.items())


def parse_meta_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"run-meta filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def run_meta_filters_match(run_meta: dict[str, Any], filters: dict[str, str]) -> bool:
    return all(k in run_meta and str(run_meta[k]) == v for k, v in filters.items())


def experiment_filters_match(run_exp: dict[str, Any], filters: dict[str, str]) -> bool:
    return all(k in run_exp and str(run_exp[k]) == v for k, v in filters.items())


def parse_tool_name_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--tool` CLI values (exact name match; OR semantics across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name:
            raise typer.BadParameter(
                "Empty --tool is not allowed; omit the flag or pass a tool `name` "
                "(exact match against JSONL `tool_call` payload `name`; repeat for OR)."
            )
        normalized.append(name)
    return frozenset(normalized)


def parse_note_kind_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--note-kind` CLI values (exact kind match; OR semantics across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        kind = str(item).strip()
        if not kind:
            raise typer.BadParameter(
                "Empty --note-kind is not allowed; omit the flag or pass a step_note `kind` "
                "(exact match against JSONL `step_note` payload `kind`; repeat for OR)."
            )
        normalized.append(kind)
    return frozenset(normalized)


def run_matches_tool_name_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "tool_call":
            continue
        payload = e.get("payload") or {}
        n = payload.get("name")
        if isinstance(n, str) and n in wanted:
            return True
    return False


def parse_structured_schema_name_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--structured-schema` values (exact `schema_name`; OR across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name:
            raise typer.BadParameter(
                "Empty --structured-schema is not allowed; omit the flag or pass a `schema_name` "
                "(exact match on `structured_output` / `structured_output_failed` events; repeat for OR)."
            )
        normalized.append(name)
    return frozenset(normalized)


def run_matches_structured_schema_name_filter(
    events: list[dict[str, Any]], wanted: frozenset[str] | None
) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") not in {"structured_output", "structured_output_failed"}:
            continue
        payload = e.get("payload") or {}
        sn = payload.get("schema_name")
        if isinstance(sn, str) and sn in wanted:
            return True
    return False


def run_matches_note_kind_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "step_note":
            continue
        payload = e.get("payload") or {}
        kind = payload.get("kind")
        if isinstance(kind, str) and kind in wanted:
            return True
    return False


def parse_finish_reason_filters(raw: list[str] | None) -> frozenset[str] | None:
    """Normalize repeatable `--finish-reason` values (exact match; OR across values)."""
    if not raw:
        return None
    normalized: list[str] = []
    for item in raw:
        reason = str(item).strip()
        if not reason:
            raise typer.BadParameter(
                "Empty --finish-reason is not allowed; omit the flag or pass an `llm_response` "
                "payload `finish_reason` string (exact match; repeat for OR)."
            )
        normalized.append(reason)
    return frozenset(normalized)


def run_matches_finish_reason_filter(events: list[dict[str, Any]], wanted: frozenset[str] | None) -> bool:
    if wanted is None:
        return True
    for e in events:
        if e.get("type") != "llm_response":
            continue
        payload = e.get("payload") or {}
        fr = payload.get("finish_reason")
        if isinstance(fr, str) and fr in wanted:
            return True
    return False


def parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def run_diff_data(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract comparable data from a run's events."""
    states: list[str] = []
    outputs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    status = "unknown"
    total_latency_ms = 0
    llm_count = 0
    for e in events:
        typ = e.get("type")
        payload = e.get("payload") or {}
        if typ == "state_entered":
            states.append(str(payload.get("state", "")))
        elif typ == "structured_output":
            outputs.append(
                {
                    "schema_name": str(payload.get("schema_name", "")),
                    "state": payload.get("state"),
                    "seq": e.get("seq"),
                    "data": payload.get("data"),
                }
            )
        elif typ == "tool_call":
            tool_calls.append({"tool": payload.get("name"), "args": payload.get("arguments")})
        elif typ == "llm_response":
            ms = payload.get("latency_ms")
            if isinstance(ms, int):
                total_latency_ms += ms
                llm_count += 1
        elif typ == "run_completed":
            status = payload.get("status", status)
        elif typ == "run_paused":
            status = "paused"
    return {
        "states_visited": states,
        "structured_outputs": outputs,
        "tool_calls": tool_calls,
        "status": status,
        "total_latency_ms": total_latency_ms,
        "llm_calls": llm_count,
    }


def parse_duration(value: str) -> int | None:
    """Parse a human duration like '90d', '24h', '30d' into seconds. Returns None on failure."""
    m = re.fullmatch(r"(\d+)\s*([dhms])", value.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return n * multipliers[unit]
