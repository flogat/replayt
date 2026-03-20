from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import typer

from replayt.graph_export import workflow_to_mermaid
from replayt.llm import LLMSettings, OpenAICompatClient
from replayt.persistence import JSONLStore, MultiStore, SQLiteStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.types import LogMode
from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec

app = typer.Typer(no_args_is_help=True, add_completion=False)


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
    if ":" in target:
        mod_name, attr = target.split(":", 1)
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, attr)
    else:
        path = Path(target)
        if not path.exists():
            raise typer.BadParameter(
                "Expected MODULE:VAR, workflow.py, or workflow.yaml target; path was not found"
            )
        if path.suffix == ".py":
            obj = _load_python_file(path)
        elif path.suffix in {".yaml", ".yml"}:
            obj = workflow_from_spec(load_workflow_yaml(path))
        else:
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


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "status": "unknown",
        "workflow_name": None,
        "workflow_version": None,
        "state_count": 0,
        "transition_count": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "approvals": 0,
        "last_ts": None,
    }
    for event in events:
        summary["last_ts"] = event.get("ts")
        typ = event.get("type")
        payload = event.get("payload") or {}
        if typ == "run_started":
            summary["workflow_name"] = payload.get("workflow_name")
            summary["workflow_version"] = payload.get("workflow_version")
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
    log_mode: str = typer.Option("redacted", case_sensitive=False, help="redacted|full"),
    resume: bool = typer.Option(False, help="Resume a paused run (requires --run-id)."),
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
    lm = LogMode.redacted if log_mode.lower() == "redacted" else LogMode.full
    store = _make_store(log_dir, sqlite)
    runner = Runner(wf, store, log_mode=lm)
    result = runner.run(run_id=run_id, resume=resume, inputs=inputs)
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"workflow={wf.name}@{wf.version}")
    typer.echo(f"status={result.status}")
    if result.error:
        typer.echo(f"error={result.error}")
        raise typer.Exit(code=1)


@app.command("inspect")
def cmd_inspect(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    as_json: bool = typer.Option(False, "--json", help="Print raw events JSON."),
) -> None:
    store = JSONLStore(log_dir)
    events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r} in {log_dir}", err=True)
        raise typer.Exit(code=2)
    if as_json:
        typer.echo(json.dumps(events, indent=2, default=str))
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


@app.command("replay")
def cmd_replay(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
) -> None:
    """Print a human-readable timeline from the recorded run (does not call model APIs)."""

    store = JSONLStore(log_dir)
    events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)
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
    lm = LogMode.redacted if log_mode.lower() == "redacted" else LogMode.full
    store = _make_store(log_dir, sqlite)
    resolve_approval_on_store(store, run_id, approval_id, approved=not reject)
    runner = Runner(wf, store, log_mode=lm)
    result = runner.run(run_id=run_id, resume=True)
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"workflow={wf.name}@{wf.version}")
    typer.echo(f"status={result.status}")
    if result.error:
        typer.echo(f"error={result.error}")
        raise typer.Exit(code=1)


@app.command("graph")
def cmd_graph(
    target: str = typer.Argument(..., metavar="TARGET"),
) -> None:
    wf = _load_target(target)
    typer.echo(workflow_to_mermaid(wf).rstrip())


@app.command("runs")
def cmd_runs(
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    limit: int = typer.Option(20, min=1, max=200),
) -> None:
    """List recent local runs from JSONL logs."""

    store = JSONLStore(log_dir)
    run_ids = sorted(store.list_run_ids(), reverse=True)[:limit]
    if not run_ids:
        typer.echo(f"No runs found in {log_dir}")
        return
    for run_id in run_ids:
        events = store.load_events(run_id)
        summary = _event_summary(events)
        typer.echo(
            f"{run_id}  {summary['status']}  "
            f"{summary['workflow_name']}@{summary['workflow_version']}  "
            f"{summary['last_ts']}"
        )


@app.command("doctor")
def cmd_doctor() -> None:
    """Check local install health for replayt's default OpenAI-compatible setup."""

    settings = LLMSettings.from_env()
    checks: list[tuple[str, bool, str]] = []
    pyver = f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}"
    checks.append(("python", True, pyver))
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
        client = OpenAICompatClient(settings)
        reachable = False
        if settings.api_key:
            with importlib.import_module("httpx").Client(timeout=5.0) as http_client:
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
