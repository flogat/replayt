from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import typer

from replayt.graph_export import workflow_to_mermaid
from replayt.persistence import JSONLStore, MultiStore, SQLiteStore
from replayt.runner import Runner, resolve_approval_on_store
from replayt.types import LogMode
from replayt.workflow import Workflow

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _load_object(path: str) -> Any:
    if ":" not in path:
        raise typer.BadParameter("Expected module:variable (e.g. examples.foo:wf)")
    mod_name, attr = path.split(":", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


def _make_store(log_dir: Path, sqlite: Path | None) -> JSONLStore | MultiStore:
    log_dir.mkdir(parents=True, exist_ok=True)
    primary = JSONLStore(log_dir)
    if sqlite is None:
        return primary
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    return MultiStore(primary, SQLiteStore(sqlite))


@app.command("run")
def cmd_run(
    target: str = typer.Argument(..., metavar="MODULE:VAR", help="Dotted module path and Workflow variable."),
    run_id: str | None = typer.Option(None, help="Optional run id (default: random UUID)."),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help='Optional JSON object merged into the run context (e.g. \'{"ticket":"..."}\').',
    ),
    log_dir: Path = typer.Option(Path(".replayt/runs"), help="Directory for JSONL run logs."),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file mirrored alongside JSONL."),
    log_mode: str = typer.Option("redacted", case_sensitive=False, help="redacted|full"),
    resume: bool = typer.Option(False, help="Resume a paused run (requires --run-id)."),
) -> None:
    if resume and not run_id:
        typer.echo("When using --resume, you must pass --run-id", err=True)
        raise typer.Exit(code=2)
    wf = _load_object(target)
    if not isinstance(wf, Workflow):
        raise typer.BadParameter(f"{target} is not a replayt.workflow.Workflow")
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
    typer.echo(f"run_id={run_id} events={len(events)}")
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
        if typ in ("state_entered", "state_exited", "transition", "run_failed", "approval_requested"):
            line += f"  {json.dumps(payload, ensure_ascii=False, default=str)[:500]}"
        typer.echo(line)


@app.command("resume")
def cmd_resume(
    target: str = typer.Argument(..., metavar="MODULE:VAR"),
    run_id: str = typer.Argument(...),
    approval_id: str = typer.Option(..., "--approval", help="Approval id to resolve."),
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve."),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    sqlite: Path | None = typer.Option(None),
    log_mode: str = typer.Option("redacted", case_sensitive=False),
) -> None:
    wf = _load_object(target)
    if not isinstance(wf, Workflow):
        raise typer.BadParameter(f"{target} is not a Workflow")
    lm = LogMode.redacted if log_mode.lower() == "redacted" else LogMode.full
    store = _make_store(log_dir, sqlite)
    resolve_approval_on_store(store, run_id, approval_id, approved=not reject)
    runner = Runner(wf, store, log_mode=lm)
    result = runner.run(run_id=run_id, resume=True)
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status}")
    if result.error:
        typer.echo(f"error={result.error}")
        raise typer.Exit(code=1)


@app.command("graph")
def cmd_graph(
    target: str = typer.Argument(..., metavar="MODULE:VAR"),
) -> None:
    wf = _load_object(target)
    if not isinstance(wf, Workflow):
        raise typer.BadParameter(f"{target} is not a Workflow")
    typer.echo(workflow_to_mermaid(wf).rstrip())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
