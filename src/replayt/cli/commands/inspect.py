"""Commands: inspect, replay, graph, validate, runs, stats, diff, gc, log-schema."""

from __future__ import annotations

import importlib.resources
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.cli.config import DEFAULT_LOG_DIR, resolve_log_dir
from replayt.cli.display import (
    event_summary,
    experiment_filters_match,
    parse_duration,
    parse_iso_ts,
    parse_meta_filters,
    parse_tag_filters,
    replay_html,
    replay_timeline_lines,
    run_diff_data,
    run_meta_filters_match,
    tags_match,
)
from replayt.cli.stores import read_store
from replayt.cli.targets import load_target
from replayt.cli.validation import inputs_json_from_options, validate_workflow_graph, validation_report
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence import JSONLStore, SQLiteStore


def cmd_inspect(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
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
    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r} in {log_dir}", err=True)
        raise typer.Exit(code=2)
    use_json = as_json or output == "json"
    if use_json:
        summary = event_summary(events)
        typer.echo(json.dumps({"summary": summary, "events": events}, indent=2, default=str))
        return
    summary = event_summary(events)
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


def cmd_replay(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
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

    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)
    if format == "html":
        doc = replay_html(run_id, events)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(doc, encoding="utf-8")
            typer.echo(f"wrote {out}")
        else:
            typer.echo(doc)
        return
    for line in replay_timeline_lines(events):
        typer.echo(line)


def cmd_graph(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR, workflow.py, or workflow.yaml. "
            "Loading a .py file executes that file as code—use only trusted paths."
        ),
    ),
) -> None:
    wf = load_target(target)
    typer.echo(workflow_to_mermaid(wf).rstrip())


def cmd_validate(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR, workflow.py, or workflow.yaml. "
            "Loading a .py file executes that file as code—use only trusted paths."
        ),
    ),
    strict_graph: bool = typer.Option(
        False,
        "--strict-graph",
        help="Require declared transitions when the workflow has 2+ states.",
    ),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help="Optional JSON object — validated as parseable only (same as dry-check).",
    ),
    inputs_file: Path | None = typer.Option(
        None,
        "--inputs-file",
        help="Inputs JSON file (mutually exclusive with --inputs-json).",
    ),
    metadata_json: str | None = typer.Option(
        None,
        "--metadata-json",
        help="Optional metadata JSON object (parse check).",
    ),
    experiment_json: str | None = typer.Option(
        None,
        "--experiment-json",
        help="Optional experiment JSON object (parse check).",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (default) or json (machine-readable report; exit 1 when not ok).",
    ),
) -> None:
    """Validate a workflow graph without calling any LLM (useful in CI)."""

    wf = load_target(target)
    errors, warnings = validate_workflow_graph(wf, strict_graph=strict_graph)
    inputs_resolved = inputs_json_from_options(inputs_json, inputs_file)
    report = validation_report(
        target=target,
        wf=wf,
        strict_graph=strict_graph,
        errors=errors,
        warnings=warnings,
        inputs_json=inputs_resolved,
        metadata_json=metadata_json,
        experiment_json=experiment_json,
    )
    if output == "json":
        typer.echo(json.dumps(report, indent=2))
        raise typer.Exit(code=0 if report["ok"] else 1)
    if not report["ok"]:
        typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
        for err in report["errors"]:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)
    for w in warnings:
        typer.echo(f"Warning: {w}", err=True)
    typer.echo(
        f"OK: {wf.name}@{wf.version} ({len(wf.step_names())} states, {len(wf.edges())} edges)"
    )


def cmd_runs(
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    limit: int = typer.Option(20, min=1, max=200),
    tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag key=value (repeatable)."),
    run_meta: list[str] | None = typer.Option(
        None,
        "--run-meta",
        help="Filter by run_metadata key=value (string match; repeatable).",
    ),
    experiment: list[str] | None = typer.Option(
        None,
        "--experiment",
        help="Filter by run_started.experiment key=value (string match; repeatable).",
    ),
) -> None:
    """List recent local runs from JSONL logs."""

    tag_filters = parse_tag_filters(tag)
    meta_filters = parse_meta_filters(run_meta)
    exp_filters = parse_tag_filters(experiment)
    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        run_ids = sorted(store.list_run_ids(), reverse=True)
        runs_data: list[tuple[str, dict[str, Any]]] = []
        for rid in run_ids:
            if len(runs_data) >= limit:
                break
            events = store.load_events(rid)
            summary = event_summary(events)
            if tag_filters and not tags_match(summary.get("tags") or {}, tag_filters):
                continue
            if meta_filters and not run_meta_filters_match(summary.get("run_metadata") or {}, meta_filters):
                continue
            if exp_filters and not experiment_filters_match(summary.get("experiment") or {}, exp_filters):
                continue
            runs_data.append((rid, summary))
    for rid, summary in runs_data:
        typer.echo(
            f"{rid}  {summary['status']}  "
            f"{summary['workflow_name']}@{summary['workflow_version']}  "
            f"{summary['last_ts']}"
        )
    if not runs_data:
        typer.echo(f"No runs found in {log_dir}")


def cmd_stats(
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, help="Directory of JSONL run logs."),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    days: int | None = typer.Option(
        None,
        "--days",
        min=1,
        help="Only include runs whose last event is within this many days (UTC).",
    ),
    max_runs: int | None = typer.Option(
        None,
        "--max-runs",
        min=1,
        help="Load at most this many runs (by run_id descending) to limit memory use on large log dirs.",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag key=value (repeatable)."),
    run_meta: list[str] | None = typer.Option(None, "--run-meta", help="Filter by run_metadata key=value."),
    experiment: list[str] | None = typer.Option(
        None,
        "--experiment",
        help="Filter by run_started.experiment key=value (repeatable).",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Summarize local run logs: counts, LLM latency averages, token usage, common failure states."""

    tag_filters = parse_tag_filters(tag)
    meta_filters = parse_meta_filters(run_meta)
    exp_filters = parse_tag_filters(experiment)
    log_dir = resolve_log_dir(log_dir, log_subdir)
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

    with read_store(log_dir, sqlite) as store:
        all_run_ids = store.list_run_ids()
        run_ids = all_run_ids
        if max_runs is not None:
            run_ids = sorted(all_run_ids, reverse=True)[:max_runs]
        all_run_events = [(rid, store.load_events(rid)) for rid in run_ids]

    for rid, events in all_run_events:
        if not events:
            continue
        summ = event_summary(events)
        last_event_ts = parse_iso_ts(summ.get("last_ts"))
        if cutoff is not None and last_event_ts is not None and last_event_ts < cutoff:
            continue
        if tag_filters and not tags_match(summ.get("tags") or {}, tag_filters):
            continue
        if meta_filters and not run_meta_filters_match(summ.get("run_metadata") or {}, meta_filters):
            continue
        if exp_filters and not experiment_filters_match(summ.get("experiment") or {}, exp_filters):
            continue
        total += 1
        st = str(summ.get("status", "unknown"))
        by_status[st] += 1
        for e in events:
            t = parse_iso_ts(e.get("ts"))
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
        "runs_total_on_disk": len(all_run_ids),
        "runs_scanned": len(run_ids),
        "max_runs": max_runs,
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
    typer.echo(f"runs_included={total} (on_disk={len(all_run_ids)}, scanned={len(run_ids)})")
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


def cmd_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o"),
) -> None:
    """Compare two runs side by side: states, outputs, tool calls, status, latency."""

    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events_a = store.load_events(run_a)
        events_b = store.load_events(run_b)
    if not events_a:
        typer.echo(f"No events for run_id={run_a!r}", err=True)
        raise typer.Exit(code=2)
    if not events_b:
        typer.echo(f"No events for run_id={run_b!r}", err=True)
        raise typer.Exit(code=2)

    da = run_diff_data(events_a)
    db = run_diff_data(events_b)

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


def cmd_gc(
    older_than: str = typer.Option(..., "--older-than", help="Delete runs older than this duration (e.g. 90d, 24h)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to also garbage-collect."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted."),
) -> None:
    """Garbage-collect old run logs by last-event timestamp."""

    seconds = parse_duration(older_than)
    if seconds is None:
        raise typer.BadParameter(f"Cannot parse duration: {older_than!r} (expected e.g. 90d, 24h, 60m)")
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    log_dir = resolve_log_dir(log_dir, log_subdir)
    jsonl_store = JSONLStore(log_dir)
    sqlite_store = SQLiteStore(sqlite) if sqlite is not None else None
    run_ids = jsonl_store.list_run_ids()
    deleted = 0
    for rid in run_ids:
        events = jsonl_store.load_events(rid)
        if not events:
            continue
        last_ts_raw = events[-1].get("ts")
        last_ts = parse_iso_ts(last_ts_raw)
        if last_ts is None or last_ts >= cutoff:
            continue
        if dry_run:
            typer.echo(f"[dry-run] would delete {rid} (last_event={last_ts_raw})")
        else:
            jsonl_store.delete_run(rid)
            if sqlite_store is not None:
                sqlite_store.delete_run(rid)
            typer.echo(f"deleted {rid}")
        deleted += 1

    if sqlite_store is not None:
        sqlite_store.close()

    verb = "would delete" if dry_run else "deleted"
    typer.echo(f"\n{verb} {deleted} run(s)")


def cmd_log_schema() -> None:
    """Print the bundled JSON Schema for one JSONL event object (stdout, machine-readable)."""

    path = importlib.resources.files("replayt").joinpath("schemas/run_log_event_line.schema.json")
    typer.echo(path.read_text(encoding="utf-8"))


def register(app: typer.Typer) -> None:
    app.command("inspect")(cmd_inspect)
    app.command("replay")(cmd_replay)
    app.command("graph")(cmd_graph)
    app.command("validate")(cmd_validate)
    app.command("runs")(cmd_runs)
    app.command("stats")(cmd_stats)
    app.command("diff")(cmd_diff)
    app.command("gc")(cmd_gc)
    app.command("log-schema")(cmd_log_schema)
