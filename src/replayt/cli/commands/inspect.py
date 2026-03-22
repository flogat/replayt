"""Commands: inspect, replay, graph, contract, validate, runs, stats, diff, gc, log-schema."""

from __future__ import annotations

import difflib
import importlib.resources
import json
from collections import Counter
from datetime import datetime, timezone
from itertools import zip_longest
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
    parse_note_kind_filters,
    parse_tag_filters,
    parse_tool_name_filters,
    replay_html,
    replay_timeline_lines,
    run_diff_data,
    run_matches_note_kind_filter,
    run_matches_tool_name_filter,
    run_meta_filters_match,
    tags_match,
)
from replayt.cli.run_id_hints import echo_missing_run_hints
from replayt.cli.stores import read_store
from replayt.cli.targets import load_target
from replayt.cli.validation import inputs_json_from_options, validate_workflow_graph, validation_report
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence import JSONLStore, SQLiteStore

_RUN_STATUS_CHOICES = frozenset({"completed", "failed", "paused", "unknown"})
_WORKFLOW_CONTRACT_SCHEMA = "replayt.workflow_contract.v1"
_WORKFLOW_CONTRACT_CHECK_SCHEMA = "replayt.workflow_contract_check.v1"
_INSPECT_REPORT_SCHEMA = "replayt.inspect_report.v1"
_STATS_REPORT_SCHEMA = "replayt.stats_report.v1"
_DIFF_REPORT_SCHEMA = "replayt.diff_report.v1"


def _event_type_filters(event_types: list[str] | None) -> frozenset[str] | None:
    if not event_types:
        return None
    normalized: list[str] = []
    for raw in event_types:
        t = str(raw).strip()
        if not t:
            raise typer.BadParameter(
                "Empty --event-type is not allowed; omit the flag or pass a JSONL `type` string "
                "(e.g. step_note, tool_call, llm_request)."
            )
        normalized.append(t)
    return frozenset(normalized)


def _filter_events_by_type(events: list[dict[str, Any]], filters: frozenset[str] | None) -> list[dict[str, Any]]:
    if filters is None:
        return events
    return [e for e in events if e.get("type") in filters]


def _filter_events_by_note_kind(
    events: list[dict[str, Any]],
    filters: frozenset[str] | None,
    *,
    event_type_filters: frozenset[str] | None,
) -> list[dict[str, Any]]:
    if filters is None:
        return events
    filtered: list[dict[str, Any]] = []
    for event in events:
        typ = event.get("type")
        if typ == "step_note":
            payload = event.get("payload") or {}
            kind = payload.get("kind")
            if isinstance(kind, str) and kind in filters:
                filtered.append(event)
            continue
        if event_type_filters is not None and typ in event_type_filters:
            filtered.append(event)
    return filtered


def _contract_json_lines(contract: dict[str, Any]) -> list[str]:
    return json.dumps(contract, indent=2, sort_keys=True).splitlines()


def _write_contract_snapshot(path: Path, contract: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")


def _load_contract_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Contract snapshot not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Contract snapshot must be UTF-8 text: {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Contract snapshot must be valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Contract snapshot must be a JSON object: {path}")
    if data.get("schema") != _WORKFLOW_CONTRACT_SCHEMA:
        got = data.get("schema")
        raise ValueError(
            f"Contract snapshot schema mismatch: expected {_WORKFLOW_CONTRACT_SCHEMA!r}, got {got!r}"
        )
    return data


def _contract_check_report(
    current: dict[str, Any], *, expected: dict[str, Any], snapshot_path: Path
) -> dict[str, Any]:
    matches = current == expected
    diff = list(
        difflib.unified_diff(
            _contract_json_lines(expected),
            _contract_json_lines(current),
            fromfile=str(snapshot_path),
            tofile="current",
            lineterm="",
        )
    )
    return {
        "schema": _WORKFLOW_CONTRACT_CHECK_SCHEMA,
        "ok": matches,
        "snapshot_path": str(snapshot_path),
        "workflow": current.get("workflow"),
        "diff": diff,
    }


def _run_status_filters(status: list[str] | None) -> frozenset[str] | None:
    if not status:
        return None
    bad = sorted({s for s in status if s not in _RUN_STATUS_CHOICES})
    if bad:
        raise typer.BadParameter(
            f"Invalid --status {bad!r}; choose from {sorted(_RUN_STATUS_CHOICES)} (repeat for OR)."
        )
    return frozenset(status)


def cmd_inspect(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    event_type: list[str] | None = typer.Option(
        None,
        "--event-type",
        help=(
            "Only include JSONL events whose `type` matches (repeatable; OR). "
            "Summary counts still reflect the full run; the event list (and JSON `events`) are filtered."
        ),
    ),
    note_kind: list[str] | None = typer.Option(
        None,
        "--note-kind",
        help=(
            "Only include `step_note` events whose payload `kind` matches (repeatable; OR). "
            "Without --event-type, this narrows the event list to matching notes only."
        ),
    ),
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
    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    type_filters = _event_type_filters(event_type)
    note_kind_filters = parse_note_kind_filters(note_kind)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r} in {log_dir}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)
    filtered = _filter_events_by_type(events, type_filters)
    filtered = _filter_events_by_note_kind(filtered, note_kind_filters, event_type_filters=type_filters)
    use_json = as_json or output == "json"
    if use_json:
        summary = event_summary(events)
        payload: dict[str, Any] = {
            "schema": _INSPECT_REPORT_SCHEMA,
            "run_id": run_id,
            "summary": summary,
            "events": filtered,
        }
        if type_filters is not None:
            payload["event_type_filter"] = sorted(type_filters)
        if note_kind_filters is not None:
            payload["note_kind_filter"] = sorted(note_kind_filters)
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    summary = event_summary(events)
    typer.echo(
        f"run_id={run_id} workflow={summary['workflow_name']}@{summary['workflow_version']} status={summary['status']}"
    )
    event_counts = f"events={len(events)}"
    if type_filters is not None or note_kind_filters is not None:
        event_counts += f" shown={len(filtered)}"
    typer.echo(
        (
            "{event_counts} states={states} transitions={transitions} "
            "llm_calls={llm_calls} tool_calls={tool_calls} notes={notes} approvals={approvals}"
        ).format(
            event_counts=event_counts,
            states=summary["state_count"],
            transitions=summary["transition_count"],
            llm_calls=summary["llm_calls"],
            tool_calls=summary["tool_calls"],
            notes=summary["notes"],
            approvals=summary["approvals"],
        )
    )
    for e in filtered:
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

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)
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


def cmd_contract(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR, workflow.py, or workflow.yaml. "
            "Loading a .py file executes that file as code-use only trusted paths."
        ),
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (default) or json.",
    ),
    snapshot_out: Path | None = typer.Option(
        None,
        "--snapshot-out",
        help="Write the current replayt.workflow_contract.v1 JSON snapshot to this path.",
    ),
    check: Path | None = typer.Option(
        None,
        "--check",
        help="Compare the current contract against a checked-in replayt.workflow_contract.v1 JSON snapshot.",
    ),
) -> None:
    """Print a snapshot-friendly workflow contract: states, retries, expects, and declared edges."""

    if snapshot_out is not None and check is not None:
        typer.echo("Use only one of --snapshot-out or --check", err=True)
        raise typer.Exit(code=1)

    wf = load_target(target)
    contract = wf.contract()
    if snapshot_out is not None:
        _write_contract_snapshot(snapshot_out, contract)
    if check is not None:
        try:
            expected = _load_contract_snapshot(check)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        report = _contract_check_report(contract, expected=expected, snapshot_path=check)
        if output == "json":
            typer.echo(json.dumps(report, indent=2))
        else:
            if report["ok"]:
                typer.echo(f"contract matches {check}")
            else:
                typer.echo(f"contract drift against {check}", err=True)
                for line in report["diff"]:
                    typer.echo(line, err=True)
        raise typer.Exit(code=0 if report["ok"] else 1)
    if output == "json":
        typer.echo(json.dumps(contract, indent=2))
        return

    meta = contract["workflow"]
    typer.echo(
        f"{meta['name']}@{meta['version']} initial={meta['initial_state']} "
        f"states={meta['state_count']} edges={meta['edge_count']}"
    )
    if meta["meta_keys"]:
        typer.echo("meta_keys=" + ", ".join(meta["meta_keys"]))
    if meta["llm_defaults_keys"]:
        typer.echo("llm_defaults_keys=" + ", ".join(meta["llm_defaults_keys"]))
    for step in contract["steps"]:
        expects = ", ".join(f"{item['key']}:{item['type']}" for item in step["expects"]) or "-"
        outgoing = ", ".join(step["outgoing_transitions"]) or "-"
        retry = step["retry_policy"]
        typer.echo(
            f"{step['name']}: expects={expects} retries={retry['max_attempts']} "
            f"backoff={retry['backoff_seconds']} next={outgoing}"
        )
    if snapshot_out is not None:
        typer.echo(f"wrote {snapshot_out}")


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
    input_value: list[str] | None = typer.Option(
        None,
        "--input",
        help=(
            "Repeatable key=value input override. Dotted keys build nested objects "
            "(for example issue.title=Crash); values are parsed as JSON scalars/objects when possible."
        ),
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
    inputs_resolved = inputs_json_from_options(inputs_json, inputs_file, input_value)
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
    status: list[str] | None = typer.Option(
        None,
        "--status",
        help="Filter by recorded terminal status (repeatable; OR): completed, failed, paused, unknown.",
    ),
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
    tool: list[str] | None = typer.Option(
        None,
        "--tool",
        help="Only runs that recorded a `tool_call` with this `name` (exact match; repeatable; OR).",
    ),
    note_kind: list[str] | None = typer.Option(
        None,
        "--note-kind",
        help="Only runs that recorded a `step_note` with this `kind` (exact match; repeatable; OR).",
    ),
) -> None:
    """List recent local runs from JSONL logs."""

    status_filters = _run_status_filters(status)
    tag_filters = parse_tag_filters(tag)
    meta_filters = parse_meta_filters(run_meta)
    exp_filters = parse_tag_filters(experiment)
    tool_filters = parse_tool_name_filters(tool)
    note_kind_filters = parse_note_kind_filters(note_kind)
    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        runs_data: list[tuple[str, dict[str, Any]]] = []
        for rid in store.list_run_ids():
            events = store.load_events(rid)
            summary = event_summary(events)
            if tag_filters and not tags_match(summary.get("tags") or {}, tag_filters):
                continue
            if meta_filters and not run_meta_filters_match(summary.get("run_metadata") or {}, meta_filters):
                continue
            if exp_filters and not experiment_filters_match(summary.get("experiment") or {}, exp_filters):
                continue
            if status_filters is not None and summary.get("status") not in status_filters:
                continue
            if not run_matches_tool_name_filter(events, tool_filters):
                continue
            if not run_matches_note_kind_filter(events, note_kind_filters):
                continue
            runs_data.append((rid, summary))

    def _run_sort_key(item: tuple[str, dict]) -> tuple:
        rid, summary = item
        ts = parse_iso_ts(summary.get("last_ts"))
        return (ts is not None, ts, rid)

    runs_data.sort(key=_run_sort_key, reverse=True)
    runs_data = runs_data[:limit]
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
    tool: list[str] | None = typer.Option(
        None,
        "--tool",
        help="Only runs that recorded a `tool_call` with this `name` (exact match; repeatable; OR).",
    ),
    note_kind: list[str] | None = typer.Option(
        None,
        "--note-kind",
        help="Only runs that recorded a `step_note` with this `kind` (exact match; repeatable; OR).",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Summarize local run logs: counts, LLM latency averages, token usage, common failure states."""

    tag_filters = parse_tag_filters(tag)
    meta_filters = parse_meta_filters(run_meta)
    exp_filters = parse_tag_filters(experiment)
    tool_filters = parse_tool_name_filters(tool)
    note_kind_filters = parse_note_kind_filters(note_kind)
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
        if not run_matches_tool_name_filter(events, tool_filters):
            continue
        if not run_matches_note_kind_filter(events, note_kind_filters):
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
        "schema": _STATS_REPORT_SCHEMA,
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

    cli_log_dir = log_dir
    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events_a = store.load_events(run_a)
        events_b = store.load_events(run_b)
    if not events_a:
        typer.echo(f"No events for run_id={run_a!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)
    if not events_b:
        typer.echo(f"No events for run_id={run_b!r}", err=True)
        echo_missing_run_hints(cli_log_dir=cli_log_dir, log_subdir=log_subdir, sqlite=sqlite)
        raise typer.Exit(code=1)

    da = run_diff_data(events_a)
    db = run_diff_data(events_b)

    diff_payload: dict[str, Any] = {
        "schema": _DIFF_REPORT_SCHEMA,
        "run_a": run_a,
        "run_b": run_b,
        "status": {"a": da["status"], "b": db["status"], "changed": da["status"] != db["status"]},
        "states_visited": {
            "a": da["states_visited"],
            "b": db["states_visited"],
            "changed": da["states_visited"] != db["states_visited"],
        },
        "structured_outputs": {
            "a_count": len(da["structured_outputs"]),
            "b_count": len(db["structured_outputs"]),
            "changed": da["structured_outputs"] != db["structured_outputs"],
        },
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
        field_diffs: dict[str, Any] = {}
        for idx, (va, vb) in enumerate(
            zip_longest(da["structured_outputs"], db["structured_outputs"], fillvalue=None),
            start=1,
        ):
            if va != vb:
                schema_name = ""
                if isinstance(va, dict) and va.get("schema_name"):
                    schema_name = str(va["schema_name"])
                elif isinstance(vb, dict) and vb.get("schema_name"):
                    schema_name = str(vb["schema_name"])
                label = schema_name or f"output_{idx}"
                field_diffs[f"{idx}:{label}"] = {"a": va, "b": vb}
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
        for idx, (va, vb) in enumerate(
            zip_longest(da["structured_outputs"], db["structured_outputs"], fillvalue=None),
            start=1,
        ):
            if va != vb:
                schema_name = ""
                if isinstance(va, dict) and va.get("schema_name"):
                    schema_name = str(va["schema_name"])
                elif isinstance(vb, dict) and vb.get("schema_name"):
                    schema_name = str(vb["schema_name"])
                label = schema_name or str(idx)
                typer.echo(f"output[{label}#{idx}] changed:")
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
    sqlite_store = None
    if sqlite is not None:
        if not sqlite.is_file():
            typer.echo(f"SQLite store not found: {sqlite}", err=True)
            raise typer.Exit(code=1)
        sqlite_store = SQLiteStore(sqlite)
    run_ids = set(jsonl_store.list_run_ids())
    if sqlite_store is not None:
        run_ids.update(sqlite_store.list_run_ids())
    deleted = 0
    for rid in sorted(run_ids):
        copies: list[list[dict[str, Any]]] = []
        jsonl_events = jsonl_store.load_events(rid)
        if jsonl_events:
            copies.append(jsonl_events)
        if sqlite_store is not None:
            sqlite_events = sqlite_store.load_events(rid)
            if sqlite_events:
                copies.append(sqlite_events)
        if not copies:
            continue
        last_ts_raw = ""
        last_ts_values: list[datetime] = []
        unparseable_copy = False
        for events in copies:
            raw_ts = events[-1].get("ts")
            parsed_ts = parse_iso_ts(raw_ts)
            if parsed_ts is None:
                unparseable_copy = True
                break
            last_ts_raw = str(raw_ts)
            last_ts_values.append(parsed_ts)
        if unparseable_copy or not last_ts_values:
            continue
        last_ts = max(last_ts_values)
        if last_ts >= cutoff:
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
    app.command("contract")(cmd_contract)
    app.command("validate")(cmd_validate)
    app.command("runs")(cmd_runs)
    app.command("stats")(cmd_stats)
    app.command("diff")(cmd_diff)
    app.command("gc")(cmd_gc)
    app.command("log-schema")(cmd_log_schema)
