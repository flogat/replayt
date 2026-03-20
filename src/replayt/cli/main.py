from __future__ import annotations

import html
import importlib
import importlib.util
import json
import os
import re
import signal
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.graph_export import workflow_to_mermaid
from replayt.llm import LLMSettings, OpenAICompatClient
from replayt.persistence import JSONLStore, MultiStore, SQLiteStore
from replayt.runner import Runner, RunResult, resolve_approval_on_store
from replayt.types import LogMode
from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _parse_log_mode(log_mode: str) -> LogMode:
    key = log_mode.strip().lower()
    if key == "redacted":
        return LogMode.redacted
    if key == "full":
        return LogMode.full
    if key in {"structured_only", "structured-only"}:
        return LogMode.structured_only
    raise typer.BadParameter("log_mode must be redacted, full, or structured_only")


def _load_python_file(path: Path) -> Any:
    module_name = f"replayt_user_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Could not import Python workflow file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("wf", "workflow"):
        if hasattr(module, attr):
            return getattr(module, attr)
    raise typer.BadParameter(f"Python workflow file {path} must define `wf` or `workflow`")


def _load_target(target: str) -> Workflow:
    path = Path(target)
    looks_like_file = path.suffix in {".py", ".yaml", ".yml"} and path.is_file()
    if looks_like_file:
        if path.suffix == ".py":
            obj = _load_python_file(path)
        else:
            obj = workflow_from_spec(load_workflow_yaml(path))
    elif ":" in target:
        mod_name, attr = target.split(":", 1)
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, attr)
    else:
        if not path.exists():
            raise typer.BadParameter(
                "Expected MODULE:VAR, workflow.py, or workflow.yaml target; path was not found"
            )
        raise typer.BadParameter("Target must be MODULE:VAR, .py, .yaml, or .yml")
    if not isinstance(obj, Workflow):
        raise typer.BadParameter(f"{target} did not resolve to a replayt.workflow.Workflow")
    return obj


def _make_store(log_dir: Path, sqlite: Path | None) -> JSONLStore | MultiStore:
    log_dir.mkdir(parents=True, exist_ok=True)
    primary = JSONLStore(log_dir)
    if sqlite is None:
        return primary
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    return MultiStore(primary, SQLiteStore(sqlite))


def _read_store(log_dir: Path, sqlite: Path | None) -> JSONLStore | SQLiteStore:
    if sqlite is not None:
        return SQLiteStore(sqlite)
    return JSONLStore(log_dir)


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "unknown",
        "workflow_name": None,
        "workflow_version": None,
        "state_count": 0,
        "transition_count": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "approvals": 0,
        "last_ts": None,
        "tags": {},
    }
    for event in events:
        summary["last_ts"] = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}
        if typ == "run_started":
            summary["workflow_name"] = payload.get("workflow_name")
            summary["workflow_version"] = payload.get("workflow_version")
            summary["tags"] = payload.get("tags") or {}
        elif typ == "state_entered":
            summary["state_count"] += 1
        elif typ == "transition":
            summary["transition_count"] += 1
        elif typ == "llm_request":
            summary["llm_calls"] += 1
        elif typ == "tool_call":
            summary["tool_calls"] += 1
        elif typ == "approval_requested":
            summary["approvals"] += 1
        elif typ == "run_completed":
            summary["status"] = payload.get("status", summary["status"])
        elif typ == "run_paused":
            summary["status"] = "paused"
    return summary


def _exit_for_run_result(result: RunResult) -> None:
    """CLI exit codes: 0 completed, 1 failed, 2 paused (waiting for approval or similar)."""

    if result.status == "completed":
        return
    if result.status == "paused":
        raise typer.Exit(code=2)
    raise typer.Exit(code=1)


def _run_result_payload(wf: Workflow, result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "workflow": f"{wf.name}@{wf.version}",
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
    }


INIT_WORKFLOW_PY = '''"""Scaffolded replayt workflow — run with: replayt run workflow.py --inputs-json '{}' """

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("my_workflow", version="1")
wf.set_initial("hello")


@wf.step("hello")
def hello(ctx):
    ctx.set("message", "ready")
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

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


INIT_ENV_EXAMPLE = """# Copy to .env and load before running (replayt does not read .env automatically).
# Example (bash): set -a && source .env && set +a
OPENAI_API_KEY=

# Optional — OpenAI-compatible API base (overrides REPLAYT_PROVIDER preset default).
# OPENAI_BASE_URL=https://api.openai.com/v1

# Optional — default model (overrides provider preset default).
# REPLAYT_MODEL=gpt-4o-mini

# Optional — openai | ollama | groq | together | openrouter | anthropic (see README).
# REPLAYT_PROVIDER=openai
"""


@app.command("init")
def cmd_init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Directory to write scaffold files into."),
    force: bool = typer.Option(False, help="Overwrite existing workflow.py / .env.example."),
) -> None:
    """Create a minimal workflow.py and .env.example in the given directory."""

    path.mkdir(parents=True, exist_ok=True)
    wf_file = path / "workflow.py"
    env_file = path / ".env.example"
    if not force:
        if wf_file.exists() or env_file.exists():
            typer.echo(
                f"Refusing to overwrite: {wf_file} or {env_file} exists (use --force).",
                err=True,
            )
            raise typer.Exit(code=1)
    wf_file.write_text(INIT_WORKFLOW_PY, encoding="utf-8")
    env_file.write_text(INIT_ENV_EXAMPLE, encoding="utf-8")
    typer.echo(f"Wrote {wf_file}")
    typer.echo(f"Wrote {env_file}")
    typer.echo("Next: python -m venv .venv && activate, pip install replayt, export OPENAI_API_KEY=...")
    typer.echo(f"Run: replayt run {wf_file} --inputs-json '{{}}'")


@app.command("run")
def cmd_run(
    target: str = typer.Argument(..., metavar="TARGET", help="MODULE:VAR, workflow.py, or workflow.yaml."),
    run_id: str | None = typer.Option(None, help="Optional run id (default: random UUID)."),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help="Optional JSON object merged into the run context.",
    ),
    log_dir: Path = typer.Option(Path(".replayt/runs"), help="Directory for JSONL run logs."),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file mirrored alongside JSONL."),
    log_mode: str = typer.Option(
        "redacted",
        case_sensitive=False,
        help="redacted|full|structured_only (no body previews; structured_output events still logged)",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Tag as key=value (repeatable)."),
    resume: bool = typer.Option(False, help="Resume a paused run (requires --run-id)."),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Kill the run after this many seconds with exit code 1.",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--output",
        "-o",
        help="text (default) or json (machine-readable).",
    ),
) -> None:
    if resume and not run_id:
        typer.echo("When using --resume, you must pass --run-id", err=True)
        raise typer.Exit(code=2)
    wf = _load_target(target)
    inputs: dict[str, Any] | None = None
    if inputs_json is not None:
        inputs = json.loads(inputs_json)
        if not isinstance(inputs, dict):
            raise typer.BadParameter("--inputs-json must be a JSON object")
    tags_dict: dict[str, str] | None = None
    if tag:
        tags_dict = {}
        for t in tag:
            if "=" not in t:
                raise typer.BadParameter(f"Tag must be key=value, got: {t!r}")
            k, v = t.split("=", 1)
            tags_dict[k] = v
    lm = _parse_log_mode(log_mode)
    store = _make_store(log_dir, sqlite)
    runner = Runner(wf, store, log_mode=lm)
    if timeout is not None and timeout > 0:
        if sys.platform != "win32":
            def _timeout_handler(signum: int, frame: Any) -> None:
                typer.echo(f"Run timed out after {timeout}s", err=True)
                raise SystemExit(1)

            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout)
        else:
            import threading

            def _kill_after() -> None:
                typer.echo(f"Run timed out after {timeout}s", err=True)
                os._exit(1)

            timer = threading.Timer(float(timeout), _kill_after)
            timer.daemon = True
            timer.start()
    result = runner.run(run_id=run_id, resume=resume, inputs=inputs, tags=tags_dict)
    if output == "json":
        typer.echo(json.dumps(_run_result_payload(wf, result), indent=2, default=str))
    else:
        typer.echo(f"run_id={result.run_id}")
        typer.echo(f"workflow={wf.name}@{wf.version}")
        typer.echo(f"status={result.status}")
        if result.error:
            typer.echo(f"error={result.error}")
    _exit_for_run_result(result)


@app.command("inspect")
def cmd_inspect(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Same as --output json (summary + events).",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--output",
        help="text (default) or json.",
    ),
) -> None:
    store = _read_store(log_dir, sqlite)
    events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r} in {log_dir}", err=True)
        raise typer.Exit(code=2)
    use_json = as_json or output == "json"
    if use_json:
        summary = _event_summary(events)
        typer.echo(json.dumps({"summary": summary, "events": events}, indent=2, default=str))
        return
    summary = _event_summary(events)
    typer.echo(
        f"run_id={run_id} workflow={summary['workflow_name']}@{summary['workflow_version']} status={summary['status']}"
    )
    typer.echo(
        (
            "events={events} states={states} transitions={transitions} "
            "llm_calls={llm_calls} tool_calls={tool_calls} approvals={approvals}"
        ).format(
            events=len(events),
            states=summary["state_count"],
            transitions=summary["transition_count"],
            llm_calls=summary["llm_calls"],
            tool_calls=summary["tool_calls"],
            approvals=summary["approvals"],
        )
    )
    for e in events:
        typ = e.get("type")
        seq = e.get("seq")
        typer.echo(f"{seq:04d}  {typ}")


def _replay_timeline_lines(events: list[dict[str, Any]]) -> list[str]:
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
            "tool_call",
            "tool_result",
        }:
            line += f"  {json.dumps(payload, ensure_ascii=False, default=str)[:500]}"
        lines.append(line)
    return lines


def _replay_html(run_id: str, events: list[dict[str, Any]]) -> str:
    summary = _event_summary(events)
    title = html.escape(f"replayt run {run_id}")
    rows = []
    pre = '<pre class="row">'
    for line in _replay_timeline_lines(events):
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


@app.command("replay")
def cmd_replay(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    format: Literal["text", "html"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (terminal) or html (HTML page with inline styles).",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write HTML to this path instead of stdout (only with --format html).",
    ),
) -> None:
    """Print a human-readable timeline from the recorded run (does not call model APIs)."""

    store = _read_store(log_dir, sqlite)
    events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)
    if format == "html":
        doc = _replay_html(run_id, events)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(doc, encoding="utf-8")
            typer.echo(f"wrote {out}")
        else:
            typer.echo(doc)
        return
    for line in _replay_timeline_lines(events):
        typer.echo(line)


@app.command("resume")
def cmd_resume(
    target: str = typer.Argument(..., metavar="TARGET"),
    run_id: str = typer.Argument(...),
    approval_id: str = typer.Option(..., "--approval", help="Approval id to resolve."),
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve."),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    sqlite: Path | None = typer.Option(None),
    log_mode: str = typer.Option("redacted", case_sensitive=False),
) -> None:
    wf = _load_target(target)
    lm = _parse_log_mode(log_mode)
    store = _make_store(log_dir, sqlite)
    resolve_approval_on_store(store, run_id, approval_id, approved=not reject)
    runner = Runner(wf, store, log_mode=lm)
    result = runner.run(run_id=run_id, resume=True)
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"workflow={wf.name}@{wf.version}")
    typer.echo(f"status={result.status}")
    if result.error:
        typer.echo(f"error={result.error}")
    _exit_for_run_result(result)


@app.command("graph")
def cmd_graph(
    target: str = typer.Argument(..., metavar="TARGET"),
) -> None:
    wf = _load_target(target)
    typer.echo(workflow_to_mermaid(wf).rstrip())


@app.command("validate")
def cmd_validate(
    target: str = typer.Argument(..., metavar="TARGET", help="MODULE:VAR, workflow.py, or workflow.yaml."),
) -> None:
    """Validate a workflow graph without calling any LLM (useful in CI)."""

    wf = _load_target(target)
    errors: list[str] = []
    if not wf.initial_state:
        errors.append("initial state is not set (call set_initial)")
    declared = set(wf.step_names())
    edges = wf.edges()
    for src, dst in edges:
        if dst not in declared:
            errors.append(f"transition target {dst!r} (from {src!r}) is not a declared step")
        if src not in declared:
            errors.append(f"transition source {src!r} is not a declared step")

    if wf.initial_state and edges:
        reachable: set[str] = set()
        queue = [wf.initial_state]
        adj: dict[str, list[str]] = {}
        for src, dst in edges:
            adj.setdefault(src, []).append(dst)
        while queue:
            node = queue.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in reachable:
                    queue.append(neighbor)
        orphans = declared - reachable
        for orphan in sorted(orphans):
            errors.append(f"state {orphan!r} is unreachable from initial state {wf.initial_state!r}")

    for name in wf.step_names():
        try:
            wf.get_handler(name)
        except KeyError:
            errors.append(f"step {name!r} has no handler")

    if errors:
        typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK: {wf.name}@{wf.version} ({len(declared)} states, {len(edges)} edges)")


def _parse_tag_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"Tag filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def _tags_match(run_tags: dict[str, str], filters: dict[str, str]) -> bool:
    return all(run_tags.get(k) == v for k, v in filters.items())


@app.command("runs")
def cmd_runs(
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    limit: int = typer.Option(20, min=1, max=200),
    tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag key=value (repeatable)."),
) -> None:
    """List recent local runs from JSONL logs."""

    tag_filters = _parse_tag_filters(tag)
    store = _read_store(log_dir, sqlite)
    run_ids = sorted(store.list_run_ids(), reverse=True)
    shown = 0
    for run_id in run_ids:
        if shown >= limit:
            break
        events = store.load_events(run_id)
        summary = _event_summary(events)
        if tag_filters and not _tags_match(summary.get("tags") or {}, tag_filters):
            continue
        shown += 1
        typer.echo(
            f"{run_id}  {summary['status']}  "
            f"{summary['workflow_name']}@{summary['workflow_version']}  "
            f"{summary['last_ts']}"
        )
    if shown == 0:
        typer.echo(f"No runs found in {log_dir}")


def _parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@app.command("stats")
def cmd_stats(
    log_dir: Path = typer.Option(Path(".replayt/runs"), help="Directory of JSONL run logs."),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    days: int | None = typer.Option(
        None,
        "--days",
        min=1,
        help="Only include runs whose last event is within this many days (UTC).",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag key=value (repeatable)."),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Summarize local run logs: counts, LLM latency averages, token usage, common failure states."""

    tag_filters = _parse_tag_filters(tag)
    store = _read_store(log_dir, sqlite)
    run_ids = store.list_run_ids()
    now = datetime.now(timezone.utc)
    cutoff = None
    if days is not None:
        from datetime import timedelta

        cutoff = now - timedelta(days=days)

    total = 0
    by_status: Counter[str] = Counter()
    latencies: list[int] = []
    fail_states: Counter[str] = Counter()
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_all_tokens = 0

    for rid in run_ids:
        events = store.load_events(rid)
        if not events:
            continue
        summ = _event_summary(events)
        last_event_ts = _parse_iso_ts(summ.get("last_ts"))
        if cutoff is not None and last_event_ts is not None and last_event_ts < cutoff:
            continue
        if tag_filters and not _tags_match(summ.get("tags") or {}, tag_filters):
            continue
        total += 1
        st = str(summ.get("status", "unknown"))
        by_status[st] += 1
        for e in events:
            t = _parse_iso_ts(e.get("ts"))
            if t is not None:
                first_ts = t if first_ts is None or t < first_ts else first_ts
                last_ts = t if last_ts is None or t > last_ts else last_ts
            if e.get("type") == "llm_response":
                p = e.get("payload") or {}
                ms = p.get("latency_ms")
                if isinstance(ms, int):
                    latencies.append(ms)
                usage = p.get("usage")
                if isinstance(usage, dict):
                    pt = usage.get("prompt_tokens")
                    ct = usage.get("completion_tokens")
                    tt = usage.get("total_tokens")
                    if isinstance(pt, int):
                        total_prompt_tokens += pt
                    if isinstance(ct, int):
                        total_completion_tokens += ct
                    if isinstance(tt, int):
                        total_all_tokens += tt
            if e.get("type") == "run_failed":
                p = e.get("payload") or {}
                state = p.get("state")
                if state:
                    fail_states[str(state)] += 1

    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    top_fails = fail_states.most_common(5)
    payload = {
        "runs_included": total,
        "runs_total_on_disk": len(run_ids),
        "status_counts": dict(by_status),
        "llm_response_count": len(latencies),
        "llm_latency_ms_avg": avg_latency,
        "token_usage": {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_all_tokens,
        },
        "top_failure_states": [{"state": s, "count": c} for s, c in top_fails],
        "event_time_range_utc": {
            "first": first_ts.isoformat() if first_ts else None,
            "last": last_ts.isoformat() if last_ts else None,
        },
        "filter_days": days,
    }
    if output == "json":
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    if total == 0:
        typer.echo(f"No runs matched in {log_dir}" + (f" (last {days} days)" if days else ""))
        return
    typer.echo(f"log_dir={log_dir}")
    typer.echo(f"runs_included={total} (on_disk={len(run_ids)})")
    typer.echo(f"status_counts={dict(by_status)}")
    if avg_latency is not None:
        typer.echo(f"llm_latency_ms_avg={avg_latency} (n={len(latencies)})")
    else:
        typer.echo("llm_latency_ms_avg=n/a")
    if total_all_tokens > 0:
        typer.echo(
            f"token_usage: prompt={total_prompt_tokens} completion={total_completion_tokens} total={total_all_tokens}"
        )
    if top_fails:
        typer.echo("top_failure_states=" + ", ".join(f"{s}:{c}" for s, c in top_fails))
    if first_ts and last_ts:
        typer.echo(f"event_time_range_utc={first_ts.isoformat()} .. {last_ts.isoformat()}")


def _run_diff_data(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract comparable data from a run's events."""
    states: list[str] = []
    outputs: dict[str, Any] = {}
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
            outputs[str(payload.get("schema_name", ""))] = payload.get("data")
        elif typ == "tool_call":
            tool_calls.append({"tool": payload.get("tool"), "args": payload.get("args")})
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


@app.command("diff")
def cmd_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o"),
) -> None:
    """Compare two runs side by side: states, outputs, tool calls, status, latency."""

    store = JSONLStore(log_dir)
    events_a = store.load_events(run_a)
    events_b = store.load_events(run_b)
    if not events_a:
        typer.echo(f"No events for run_id={run_a!r}", err=True)
        raise typer.Exit(code=2)
    if not events_b:
        typer.echo(f"No events for run_id={run_b!r}", err=True)
        raise typer.Exit(code=2)

    da = _run_diff_data(events_a)
    db = _run_diff_data(events_b)

    diff_payload: dict[str, Any] = {
        "run_a": run_a,
        "run_b": run_b,
        "status": {"a": da["status"], "b": db["status"], "changed": da["status"] != db["status"]},
        "states_visited": {
            "a": da["states_visited"],
            "b": db["states_visited"],
            "changed": da["states_visited"] != db["states_visited"],
        },
        "structured_outputs": {"changed": da["structured_outputs"] != db["structured_outputs"]},
        "tool_calls": {
            "a_count": len(da["tool_calls"]),
            "b_count": len(db["tool_calls"]),
            "changed": da["tool_calls"] != db["tool_calls"],
        },
        "latency": {
            "a_total_ms": da["total_latency_ms"],
            "b_total_ms": db["total_latency_ms"],
            "delta_ms": db["total_latency_ms"] - da["total_latency_ms"],
        },
    }

    if da["structured_outputs"] != db["structured_outputs"]:
        all_keys = sorted(set(da["structured_outputs"]) | set(db["structured_outputs"]))
        field_diffs: dict[str, Any] = {}
        for key in all_keys:
            va = da["structured_outputs"].get(key)
            vb = db["structured_outputs"].get(key)
            if va != vb:
                field_diffs[key] = {"a": va, "b": vb}
        diff_payload["structured_outputs"]["diffs"] = field_diffs

    if output == "json":
        typer.echo(json.dumps(diff_payload, indent=2, default=str))
        return

    typer.echo(f"Comparing {run_a} vs {run_b}")
    if da["status"] != db["status"]:
        typer.echo(f"status: {da['status']} -> {db['status']}")
    else:
        typer.echo(f"status: {da['status']} (same)")
    if da["states_visited"] != db["states_visited"]:
        typer.echo(f"states_a: {' -> '.join(da['states_visited'])}")
        typer.echo(f"states_b: {' -> '.join(db['states_visited'])}")
    else:
        typer.echo(f"states: {' -> '.join(da['states_visited'])} (same)")
    if da["structured_outputs"] != db["structured_outputs"]:
        for key in sorted(set(da["structured_outputs"]) | set(db["structured_outputs"])):
            va = da["structured_outputs"].get(key)
            vb = db["structured_outputs"].get(key)
            if va != vb:
                typer.echo(f"output[{key}] changed:")
                typer.echo(f"  a: {json.dumps(va, default=str)[:300]}")
                typer.echo(f"  b: {json.dumps(vb, default=str)[:300]}")
    else:
        typer.echo("structured_outputs: (same)")
    typer.echo(f"tool_calls: a={len(da['tool_calls'])} b={len(db['tool_calls'])}")
    delta = db["total_latency_ms"] - da["total_latency_ms"]
    sign = "+" if delta >= 0 else ""
    typer.echo(f"latency: a={da['total_latency_ms']}ms b={db['total_latency_ms']}ms ({sign}{delta}ms)")


def _parse_duration(value: str) -> int | None:
    """Parse a human duration like '90d', '24h', '30d' into seconds. Returns None on failure."""
    m = re.fullmatch(r"(\d+)\s*([dhms])", value.strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return n * multipliers[unit]


@app.command("gc")
def cmd_gc(
    older_than: str = typer.Option(..., "--older-than", help="Delete runs older than this duration (e.g. 90d, 24h)."),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted."),
) -> None:
    """Garbage-collect old run logs by last-event timestamp."""

    seconds = _parse_duration(older_than)
    if seconds is None:
        raise typer.BadParameter(f"Cannot parse duration: {older_than!r} (expected e.g. 90d, 24h, 60m)")
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    store = JSONLStore(log_dir)
    run_ids = store.list_run_ids()
    deleted = 0
    freed_bytes = 0
    for rid in run_ids:
        events = store.load_events(rid)
        if not events:
            continue
        last_ts_raw = events[-1].get("ts")
        last_ts = _parse_iso_ts(last_ts_raw)
        if last_ts is None or last_ts >= cutoff:
            continue
        path = store._path(rid)
        size = path.stat().st_size if path.is_file() else 0
        if dry_run:
            typer.echo(f"[dry-run] would delete {rid} ({size} bytes, last_event={last_ts_raw})")
        else:
            path.unlink(missing_ok=True)
            typer.echo(f"deleted {rid} ({size} bytes)")
        deleted += 1
        freed_bytes += size

    verb = "would delete" if dry_run else "deleted"
    typer.echo(f"\n{verb} {deleted} run(s), {freed_bytes} bytes freed")


@app.command("doctor")
def cmd_doctor() -> None:
    """Check local install health for replayt's default OpenAI-compatible setup."""

    try:
        import replayt as _rt

        pkg_ver = getattr(_rt, "__version__", "unknown")
    except ImportError:
        pkg_ver = "unknown"

    settings = LLMSettings.from_env()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("replayt", True, pkg_ver))
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("python", True, pyver))
    prov = os.environ.get("REPLAYT_PROVIDER", "")
    checks.append(("replayt_provider", True, prov or "(unset, using openai-style defaults)"))
    checks.append(("openai_api_key", bool(settings.api_key), "set" if settings.api_key else "missing"))
    checks.append(("openai_base_url", True, settings.base_url))
    checks.append(("model", True, settings.model))
    try:
        import yaml  # type: ignore[import-not-found]

        _ = yaml
        checks.append(("yaml_extra", True, "installed"))
    except ImportError:
        checks.append(("yaml_extra", False, "missing (pip install replayt[yaml])"))

    try:
        import httpx

        client = OpenAICompatClient(settings)
        reachable = False
        if settings.api_key:
            with httpx.Client(timeout=5.0) as http_client:
                r = http_client.get(
                    settings.base_url.rstrip("/") + "/models",
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                )
                reachable = r.status_code < 500
        connectivity_detail = (
            "reachable" if reachable else "skipped" if not settings.api_key else "unreachable"
        )
        checks.append(("provider_connectivity", reachable if settings.api_key else False, connectivity_detail))
        _ = client
    except Exception as exc:  # noqa: BLE001
        checks.append(("provider_connectivity", False, str(exc)))

    for name, ok, detail in checks:
        icon = "OK" if ok else "WARN"
        typer.echo(f"[{icon}] {name}: {detail}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
