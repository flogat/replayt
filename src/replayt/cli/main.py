from __future__ import annotations

import hashlib
import html
import importlib
import importlib.resources
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.export_run import events_to_jsonl_lines
from replayt.graph_export import workflow_to_mermaid
from replayt.llm import LLMSettings
from replayt.persistence import JSONLStore, MultiStore, SQLiteStore
from replayt.runner import Runner, RunResult, resolve_approval_on_store
from replayt.types import LogMode
from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec

app = typer.Typer(no_args_is_help=True, add_completion=False)

_SUPPORTED_CONFIG_KEYS = {"log_dir", "log_mode", "sqlite", "provider", "model", "timeout", "strict_mirror"}


def _load_project_config() -> tuple[dict[str, Any], str | None]:
    """Walk up from cwd looking for ``pyproject.toml`` (``[tool.replayt]``) or ``.replaytrc.toml``.

    Returns ``(config_dict, config_path_or_None)``.
    """
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return {}, None

    cur = Path.cwd().resolve()
    for directory in (cur, *cur.parents):
        rc = directory / ".replaytrc.toml"
        if rc.is_file():
            with open(rc, "rb") as f:
                data = tomllib.load(f)
            return {k: v for k, v in data.items() if k in _SUPPORTED_CONFIG_KEYS}, str(rc)

        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            section = (data.get("tool") or {}).get("replayt")
            if isinstance(section, dict):
                return {k: v for k, v in section.items() if k in _SUPPORTED_CONFIG_KEYS}, str(pyproject)
    return {}, None


_PROJECT_CONFIG: dict[str, Any] | None = None
_PROJECT_CONFIG_PATH: str | None = None


def _get_project_config() -> tuple[dict[str, Any], str | None]:
    global _PROJECT_CONFIG, _PROJECT_CONFIG_PATH  # noqa: PLW0603
    if _PROJECT_CONFIG is None:
        _PROJECT_CONFIG, _PROJECT_CONFIG_PATH = _load_project_config()
    return _PROJECT_CONFIG, _PROJECT_CONFIG_PATH


_DEFAULT_LOG_DIR = Path(".replayt/runs")


def _sanitize_log_subdir(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise typer.BadParameter("log_subdir must be non-empty")
    if os.path.sep in s or (os.altsep and os.altsep in s):
        raise typer.BadParameter("log_subdir must be a single path segment (no slashes)")
    if s.startswith(".") or s in (".", ".."):
        raise typer.BadParameter("log_subdir cannot start with '.'")
    return s


def _resolve_log_dir(cli_log_dir: Path, log_subdir: str | None = None) -> Path:
    """Apply ``[tool.replayt]`` / ``REPLAYT_LOG_DIR`` defaults and optional tenant subdir."""

    cfg, _ = _get_project_config()
    base = cli_log_dir
    if cli_log_dir == _DEFAULT_LOG_DIR:
        if cfg.get("log_dir"):
            base = Path(str(cfg["log_dir"]))
        else:
            env_ld = os.environ.get("REPLAYT_LOG_DIR")
            if env_ld:
                base = Path(env_ld)
    if log_subdir is not None:
        base = base / _sanitize_log_subdir(log_subdir)
    return base


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


def _validate_workflow(wf: Workflow) -> list[str]:
    """Graph / handler checks without executing steps (no LLM)."""

    errors: list[str] = []
    if not wf.initial_state:
        errors.append("initial state is not set (call set_initial)")
    declared = set(wf.step_names())
    if wf.initial_state and wf.initial_state not in declared:
        errors.append(f"initial state {wf.initial_state!r} is not a declared @wf.step")
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
    return errors


def _dry_check_suggested_command(
    *,
    target: str,
    inputs_json: str | None,
    log_dir: Path,
    sqlite: Path | None,
    log_mode: str,
    tag: list[str] | None,
    dry_run: bool,
) -> str:
    parts = ["replayt", "run", target, "--log-dir", str(log_dir), "--log-mode", log_mode]
    if sqlite is not None:
        parts.extend(["--sqlite", str(sqlite)])
    if inputs_json is not None:
        parts.extend(["--inputs-json", inputs_json])
    if tag:
        for t in tag:
            parts.extend(["--tag", t])
    if dry_run:
        parts.append("--dry-run")
    return " ".join(parts)


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


def _make_store(log_dir: Path, sqlite: Path | None, *, strict_mirror: bool = False) -> JSONLStore | MultiStore:
    log_dir.mkdir(parents=True, exist_ok=True)
    primary = JSONLStore(log_dir)
    if sqlite is None:
        return primary
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    return MultiStore(primary, SQLiteStore(sqlite), strict_mirror=strict_mirror)


def _build_internal_run_argv(
    *,
    target: str,
    run_id: str | None,
    inputs_json: str | None,
    log_dir: Path,
    sqlite: Path | None,
    log_mode: str,
    tag: list[str] | None,
    resume: bool,
    dry_run: bool,
    output: str,
    metadata_json: str | None = None,
) -> list[str]:
    """Argv for ``python -m replayt.cli.main`` (must not include ``--timeout`` — parent enforces that)."""

    argv = ["run", target, "--log-dir", str(log_dir), "--log-mode", log_mode, "--output", output]
    if run_id:
        argv += ["--run-id", run_id]
    if inputs_json is not None:
        argv += ["--inputs-json", inputs_json]
    if sqlite is not None:
        argv += ["--sqlite", str(sqlite)]
    if tag:
        for t in tag:
            argv += ["--tag", t]
    if metadata_json is not None:
        argv += ["--metadata-json", metadata_json]
    if resume:
        argv.append("--resume")
    if dry_run:
        argv.append("--dry-run")
    return argv


def _subprocess_env_child() -> dict[str, str]:
    """Environment for isolated ``replayt run`` children (timeout). Ensures ``replayt`` is importable."""
    env = {**os.environ, "REPLAYT_SUBPROCESS_RUN": "1"}
    for p in sys.path:
        if not p:
            continue
        try:
            if Path(p, "replayt", "__init__.py").is_file():
                prev = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = f"{p}{os.pathsep}{prev}" if prev else p
                break
        except OSError:
            continue
    return env


@contextmanager
def _read_store(log_dir: Path, sqlite: Path | None) -> Iterator[JSONLStore | SQLiteStore]:
    if sqlite is not None:
        store = SQLiteStore(sqlite)
        try:
            yield store
        finally:
            store.close()
    else:
        yield JSONLStore(log_dir)


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
        "run_metadata": {},
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

INIT_GITIGNORE_LINES = [".replayt/", ".env", ".venv/", "__pycache__/"]


def _merge_gitignore(directory: Path) -> None:
    """Ensure common local-only paths are ignored (append if .gitignore exists)."""

    path = directory / ".gitignore"
    if not path.exists():
        path.write_text("\n".join(INIT_GITIGNORE_LINES) + "\n", encoding="utf-8")
        typer.echo(f"Wrote {path}")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    have = set(lines)
    to_add = [ln for ln in INIT_GITIGNORE_LINES if ln not in have]
    if not to_add:
        return
    extra = "\n\n# replayt init\n" + "\n".join(to_add) + "\n"
    path.write_text(path.read_text(encoding="utf-8").rstrip() + extra, encoding="utf-8")
    typer.echo(f"Updated {path} ({', '.join(to_add)})")


@app.command("init")
def cmd_init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Directory to write scaffold files into."),
    force: bool = typer.Option(False, help="Overwrite existing workflow.py / .env.example."),
    template: str = typer.Option("basic", "--template", "-t", help="basic|approval|tool-using|yaml"),
) -> None:
    """Create a minimal workflow file and .env.example in the given directory."""

    from replayt.cli.templates import TEMPLATES

    if template not in TEMPLATES:
        raise typer.BadParameter(f"Unknown template {template!r}; choose from: {', '.join(sorted(TEMPLATES))}")

    content, filename = TEMPLATES[template]
    path.mkdir(parents=True, exist_ok=True)
    wf_file = path / filename
    env_file = path / ".env.example"
    if not force:
        if wf_file.exists() or env_file.exists():
            typer.echo(
                f"Refusing to overwrite: {wf_file} or {env_file} exists (use --force).",
                err=True,
            )
            raise typer.Exit(code=1)
    wf_file.write_text(content, encoding="utf-8")
    env_file.write_text(INIT_ENV_EXAMPLE, encoding="utf-8")
    _merge_gitignore(path)
    typer.echo(f"Wrote {wf_file} (template={template})")
    typer.echo(f"Wrote {env_file}")
    typer.echo("Next steps:")
    typer.echo("  1) python -m venv .venv && activate   # then: pip install replayt")
    typer.echo("  2) replayt doctor                     # see docs/QUICKSTART.md if anything is WARN")
    typer.echo("  3) export OPENAI_API_KEY=...           # only for live LLM examples")
    typer.echo(f"  4) replayt run {wf_file} --inputs-json '{{}}'")


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
    log_subdir: str | None = typer.Option(
        None,
        "--log-subdir",
        help="Single path segment appended to resolved log dir (tenant isolation); see REPLAYT_LOG_DIR.",
    ),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file mirrored alongside JSONL."),
    log_mode: str = typer.Option(
        "redacted",
        case_sensitive=False,
        help=(
            "redacted|full|structured_only (minimal LLM logs—no message text; structured_output still logged)"
        ),
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Tag as key=value (repeatable)."),
    metadata_json: str | None = typer.Option(
        None,
        "--metadata-json",
        help="JSON object on run_started as run_metadata (string values filterable via replayt runs --run-meta).",
    ),
    resume: bool = typer.Option(False, help="Resume a paused run (requires --run-id)."),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Kill the run after this many seconds (exit 1). Uses an isolated subprocess on all platforms.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Trace execution with placeholder LLM responses (no API calls)."
    ),
    dry_check: bool = typer.Option(
        False,
        "--dry-check",
        help="Validate workflow graph and --inputs-json only; no run, no LLM, no log files written.",
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

    in_child = os.environ.get("REPLAYT_SUBPROCESS_RUN") == "1"
    cfg, _ = _get_project_config()
    strict_mirror = bool(cfg.get("strict_mirror"))

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    if sqlite is None and cfg.get("sqlite"):
        sqlite = Path(cfg["sqlite"])
    if log_mode == "redacted" and cfg.get("log_mode"):
        log_mode = cfg["log_mode"]
    if not in_child and timeout is None and cfg.get("timeout"):
        timeout = int(cfg["timeout"])
    if in_child:
        timeout = None

    wf = _load_target(target)

    if dry_check:
        if resume:
            typer.echo("--dry-check cannot be used with --resume", err=True)
            raise typer.Exit(code=2)
        errors = _validate_workflow(wf)
        if inputs_json is not None:
            parsed = json.loads(inputs_json)
            if not isinstance(parsed, dict):
                raise typer.BadParameter("--inputs-json must be a JSON object")
        if metadata_json is not None:
            parsed_m = json.loads(metadata_json)
            if not isinstance(parsed_m, dict):
                raise typer.BadParameter("--metadata-json must be a JSON object")
            json.dumps(parsed_m)
        if errors:
            typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
            for err in errors:
                typer.echo(f"  - {err}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"OK: {wf.name}@{wf.version} (dry check passed; no run executed)")
        typer.echo(
            "Next: "
            + _dry_check_suggested_command(
                target=target,
                inputs_json=inputs_json,
                log_dir=log_dir,
                sqlite=sqlite,
                log_mode=log_mode,
                tag=tag,
                dry_run=dry_run,
            )
        )
        return

    errors = _validate_workflow(wf)
    if errors:
        typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)

    if not in_child and timeout is not None and timeout > 0:
        argv = _build_internal_run_argv(
            target=target,
            run_id=run_id,
            inputs_json=inputs_json,
            log_dir=log_dir,
            sqlite=sqlite,
            log_mode=log_mode,
            tag=tag,
            resume=resume,
            dry_run=dry_run,
            output=output,
            metadata_json=metadata_json,
        )
        env = _subprocess_env_child()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "replayt.cli.main", *argv],
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            typer.echo(f"Run timed out after {timeout}s", err=True)
            raise typer.Exit(code=1)
        rc = completed.returncode if completed.returncode is not None else 1
        raise typer.Exit(code=rc)

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
    run_meta: dict[str, Any] | None = None
    if metadata_json is not None:
        parsed_m = json.loads(metadata_json)
        if not isinstance(parsed_m, dict):
            raise typer.BadParameter("--metadata-json must be a JSON object")
        try:
            json.dumps(parsed_m)
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter("--metadata-json must be JSON-serializable") from exc
        run_meta = parsed_m
    lm = _parse_log_mode(log_mode)
    store = _make_store(log_dir, sqlite, strict_mirror=strict_mirror)
    if dry_run:
        from replayt.testing import DryRunLLMClient

        typer.echo("Dry run: LLM calls return placeholder responses")
        runner = Runner(wf, store, log_mode=lm, llm_client=DryRunLLMClient())
    else:
        runner = Runner(wf, store, log_mode=lm)
    try:
        result = runner.run(
            run_id=run_id,
            resume=resume,
            inputs=inputs,
            tags=tags_dict,
            run_metadata=run_meta,
        )
    except KeyboardInterrupt:
        raise typer.Exit(code=1)
    finally:
        runner.close()
    if output == "json":
        typer.echo(json.dumps(_run_result_payload(wf, result), indent=2, default=str))
    else:
        typer.echo(f"run_id={result.run_id}")
        typer.echo(f"workflow={wf.name}@{wf.version}")
        typer.echo(f"status={result.status}")
        if result.error:
            typer.echo(f"error={result.error}")
    _exit_for_run_result(result)


@app.command("try")
def cmd_try(
    ctx: typer.Context,
    log_dir: Path = typer.Option(Path(".replayt/runs"), help="Directory for JSONL run logs."),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite mirror."),
    log_mode: str = typer.Option(
        "redacted",
        case_sensitive=False,
        help="redacted|full|structured_only",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Tag as key=value (repeatable)."),
    run_id: str | None = typer.Option(None, help="Optional run id (default: random UUID)."),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Kill the run after this many seconds (exit 1). Uses an isolated subprocess on all platforms.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Placeholder LLM responses (no API calls)."),
    dry_check: bool = typer.Option(False, "--dry-check", help="Validate only; same as replayt run --dry-check."),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--output",
        "-o",
        help="text (default) or json (machine-readable).",
    ),
    customer_name: str = typer.Option("Sam", "--customer-name", help="Value for tutorial key customer_name."),
) -> None:
    """Run the packaged hello-world tutorial (``replayt_examples.e01_hello_world``); no local workflow file needed."""

    return ctx.invoke(
        cmd_run,
        target="replayt_examples.e01_hello_world:wf",
        run_id=run_id,
        inputs_json=json.dumps({"customer_name": customer_name}),
        log_dir=log_dir,
        log_subdir=None,
        sqlite=sqlite,
        log_mode=log_mode,
        tag=tag,
        metadata_json=None,
        resume=False,
        timeout=timeout,
        dry_run=dry_run,
        dry_check=dry_check,
        output=output,
    )


@app.command("ci")
def cmd_ci(
    ctx: typer.Context,
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
        help="redacted|full|structured_only",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Tag as key=value (repeatable)."),
    resume: bool = typer.Option(False, help="Resume a paused run (requires --run-id)."),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Kill the run after this many seconds (exit 1). Uses an isolated subprocess on all platforms.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Trace execution with placeholder LLM responses (no API calls).",
    ),
    dry_check: bool = typer.Option(
        False,
        "--dry-check",
        help="Validate workflow graph and --inputs-json only; no run, no LLM.",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--output",
        "-o",
        help="text (default) or json (machine-readable).",
    ),
) -> None:
    """Same as ``replayt run``; intended for CI (exit 2 = paused / approval pending)."""

    typer.echo(
        "replayt ci: exit 0=completed, 1=failed, 2=paused (e.g. approval). See docs/RECIPES.md.",
        err=True,
    )
    return ctx.invoke(
        cmd_run,
        target=target,
        run_id=run_id,
        inputs_json=inputs_json,
        log_dir=log_dir,
        log_subdir=None,
        sqlite=sqlite,
        log_mode=log_mode,
        tag=tag,
        metadata_json=None,
        resume=resume,
        timeout=timeout,
        dry_run=dry_run,
        dry_check=dry_check,
        output=output,
    )


@app.command("inspect")
def cmd_inspect(
    run_id: str = typer.Argument(...),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
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
    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
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
            raw = json.dumps(payload, ensure_ascii=False, default=str)
            if len(raw) > 500:
                raw = raw[:497] + "..."
            line += f"  {raw}"
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

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
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
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None),
    log_mode: str = typer.Option("redacted", case_sensitive=False),
) -> None:
    cfg, _ = _get_project_config()
    strict_mirror = bool(cfg.get("strict_mirror"))
    log_dir = _resolve_log_dir(log_dir, log_subdir)
    if sqlite is None and cfg.get("sqlite"):
        sqlite = Path(cfg["sqlite"])
    if log_mode == "redacted" and cfg.get("log_mode"):
        log_mode = cfg["log_mode"]
    wf = _load_target(target)
    lm = _parse_log_mode(log_mode)
    store = _make_store(log_dir, sqlite, strict_mirror=strict_mirror)
    resolve_approval_on_store(store, run_id, approval_id, approved=not reject)
    runner = Runner(wf, store, log_mode=lm)
    try:
        result = runner.run(run_id=run_id, resume=True)
    finally:
        runner.close()
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
    errors = _validate_workflow(wf)

    if errors:
        typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"OK: {wf.name}@{wf.version} ({len(wf.step_names())} states, {len(wf.edges())} edges)"
    )


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


def _parse_meta_filters(raw: list[str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for t in raw:
        if "=" not in t:
            raise typer.BadParameter(f"run-meta filter must be key=value, got: {t!r}")
        k, v = t.split("=", 1)
        out[k] = v
    return out


def _run_meta_filters_match(run_meta: dict[str, Any], filters: dict[str, str]) -> bool:
    return all(k in run_meta and str(run_meta[k]) == v for k, v in filters.items())


@app.command("runs")
def cmd_runs(
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    limit: int = typer.Option(20, min=1, max=200),
    tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag key=value (repeatable)."),
    run_meta: list[str] | None = typer.Option(
        None,
        "--run-meta",
        help="Filter by run_metadata key=value (string match; repeatable).",
    ),
) -> None:
    """List recent local runs from JSONL logs."""

    tag_filters = _parse_tag_filters(tag)
    meta_filters = _parse_meta_filters(run_meta)
    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
        run_ids = sorted(store.list_run_ids(), reverse=True)
        runs_data: list[tuple[str, dict[str, Any]]] = []
        for run_id in run_ids:
            if len(runs_data) >= limit:
                break
            events = store.load_events(run_id)
            summary = _event_summary(events)
            if tag_filters and not _tags_match(summary.get("tags") or {}, tag_filters):
                continue
            if meta_filters and not _run_meta_filters_match(summary.get("run_metadata") or {}, meta_filters):
                continue
            runs_data.append((run_id, summary))
    for run_id, summary in runs_data:
        typer.echo(
            f"{run_id}  {summary['status']}  "
            f"{summary['workflow_name']}@{summary['workflow_version']}  "
            f"{summary['last_ts']}"
        )
    if not runs_data:
        typer.echo(f"No runs found in {log_dir}")


def _parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@app.command("stats")
def cmd_stats(
    log_dir: Path = typer.Option(Path(".replayt/runs"), help="Directory of JSONL run logs."),
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
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Summarize local run logs: counts, LLM latency averages, token usage, common failure states."""

    tag_filters = _parse_tag_filters(tag)
    meta_filters = _parse_meta_filters(run_meta)
    log_dir = _resolve_log_dir(log_dir, log_subdir)
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

    with _read_store(log_dir, sqlite) as store:
        all_run_ids = store.list_run_ids()
        run_ids = all_run_ids
        if max_runs is not None:
            run_ids = sorted(all_run_ids, reverse=True)[:max_runs]
        all_run_events = [(rid, store.load_events(rid)) for rid in run_ids]

    for rid, events in all_run_events:
        if not events:
            continue
        summ = _event_summary(events)
        last_event_ts = _parse_iso_ts(summ.get("last_ts"))
        if cutoff is not None and last_event_ts is not None and last_event_ts < cutoff:
            continue
        if tag_filters and not _tags_match(summ.get("tags") or {}, tag_filters):
            continue
        if meta_filters and not _run_meta_filters_match(summ.get("run_metadata") or {}, meta_filters):
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


@app.command("diff")
def cmd_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(Path(".replayt/runs")),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to read from instead of JSONL."),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o"),
) -> None:
    """Compare two runs side by side: states, outputs, tool calls, status, latency."""

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
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
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file to also garbage-collect."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted."),
) -> None:
    """Garbage-collect old run logs by last-event timestamp."""

    seconds = _parse_duration(older_than)
    if seconds is None:
        raise typer.BadParameter(f"Cannot parse duration: {older_than!r} (expected e.g. 90d, 24h, 60m)")
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    log_dir = _resolve_log_dir(log_dir, log_subdir)
    jsonl_store = JSONLStore(log_dir)
    sqlite_store = SQLiteStore(sqlite) if sqlite is not None else None
    run_ids = jsonl_store.list_run_ids()
    deleted = 0
    for rid in run_ids:
        events = jsonl_store.load_events(rid)
        if not events:
            continue
        last_ts_raw = events[-1].get("ts")
        last_ts = _parse_iso_ts(last_ts_raw)
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


@app.command("seal")
def cmd_seal(
    run_id: str = typer.Argument(..., help="Run id (JSONL file basename without .jsonl)."),
    log_dir: Path = typer.Option(Path(".replayt/runs"), "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Manifest output path (default: <log-dir>/<run_id>.seal.json).",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Write a SHA-256 manifest for a JSONL run log (best-effort audit helper; not cryptographic proof)."""

    log_dir = _resolve_log_dir(log_dir, log_subdir)

    path = log_dir / f"{run_id}.jsonl"
    if not path.is_file():
        typer.echo(
            f"No JSONL at {path} (``seal`` applies to the primary JSONL file, not SQLite-only stores).",
            err=True,
        )
        raise typer.Exit(code=2)

    raw = path.read_bytes()
    file_digest = hashlib.sha256(raw).hexdigest()
    line_digests = [hashlib.sha256(line).hexdigest() for line in raw.splitlines(keepends=True)]
    manifest: dict[str, Any] = {
        "schema": "replayt.seal.v1",
        "run_id": run_id,
        "jsonl_path": str(path.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(line_digests),
        "line_sha256": line_digests,
        "file_sha256": file_digest,
        "note": (
            "Best-effort integrity record. Anyone who can write the log directory can replace "
            "both the JSONL and this manifest; use WORM storage or external signing for stronger guarantees."
        ),
    }
    out_path = out if out is not None else log_dir / f"{run_id}.seal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if output == "json":
        typer.echo(json.dumps({**manifest, "manifest_path": str(out_path.resolve())}, indent=2))
    else:
        typer.echo(f"wrote {out_path} ({len(line_digests)} lines, file_sha256={file_digest[:12]}...)")


@app.command("doctor")
def cmd_doctor(
    skip_connectivity: bool = typer.Option(
        False,
        "--skip-connectivity",
        help="Do not HTTP GET OPENAI_BASE_URL/models (no network; use when base URL is sensitive or untrusted).",
    ),
) -> None:
    """Check local install health for replayt's default OpenAI-compatible setup.

    Without ``--skip-connectivity``, this command sends a request to ``OPENAI_BASE_URL`` (see README
    security notes): the URL and optional API key come from your environment—only use connectivity
    checks against hosts you trust.
    """

    try:
        import replayt as _rt

        pkg_ver = getattr(_rt, "__version__", "unknown")
    except ImportError:
        pkg_ver = "unknown"

    cfg, cfg_path = _get_project_config()
    settings = LLMSettings.from_env()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("replayt", True, pkg_ver))
    if cfg_path:
        checks.append(("project_config", True, cfg_path))
    else:
        checks.append(("project_config", False, "No project config found"))
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

    if skip_connectivity:
        checks.append(("provider_connectivity", True, "skipped (--skip-connectivity)"))
    else:
        try:
            import httpx

            with httpx.Client(timeout=5.0) as http_client:
                headers: dict[str, str] = {}
                if settings.api_key:
                    headers["Authorization"] = f"Bearer {settings.api_key}"
                r = http_client.get(settings.base_url.rstrip("/") + "/models", headers=headers)
            # Any sub-5xx response means something answered; 404 is common when /models is absent (chat may still work).
            reachable = r.status_code < 500
            detail = f"HTTP {r.status_code}"
            if r.status_code == 404:
                detail += " (/models not implemented — try a chat request)"
            connectivity_detail = detail if reachable else f"{detail} (server error)"
            checks.append(("provider_connectivity", reachable, connectivity_detail))
        except Exception as exc:  # noqa: BLE001
            checks.append(("provider_connectivity", False, str(exc)))

    hints = {
        "openai_api_key": "export OPENAI_API_KEY=… (see docs/QUICKSTART.md)",
        "yaml_extra": "pip install 'replayt[yaml]' for .yaml workflow targets",
        "project_config": "optional [tool.replayt] — docs/CONFIG.md",
        "provider_connectivity": "try replayt doctor --skip-connectivity; check OPENAI_BASE_URL",
    }
    for name, ok, detail in checks:
        icon = "OK" if ok else "WARN"
        typer.echo(f"[{icon}] {name}: {detail}")
        if not ok and name in hints:
            typer.echo(f"       → {hints[name]}")


@app.command("report")
def cmd_report(
    run_id: str = typer.Argument(..., help="Run ID to generate report for"),
    log_dir: Path = typer.Option(Path(".replayt/runs"), "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Output file path (default: stdout)"),
    style: Literal["default", "stakeholder"] = typer.Option(
        "default",
        "--style",
        help="default (full) or stakeholder (approvals-first; omits tool/token sections).",
    ),
) -> None:
    """Generate a self-contained HTML report for a run."""

    from replayt.cli.report_template import (
        APPROVAL_ITEM,
        APPROVALS_SECTION,
        OUTPUT_ITEM,
        OUTPUTS_SECTION,
        REPORT_HTML,
        TIMELINE_ITEM,
        TOKEN_USAGE_SECTION,
        TOOL_CALL_ITEM,
        TOOL_CALLS_SECTION,
    )

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    workflow_name = ""
    workflow_version = ""
    status = "unknown"
    tags: dict[str, str] = {}
    run_metadata: dict[str, Any] = {}
    states: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    first_ts: str | None = None
    last_ts: str | None = None
    approval_requests: dict[str, dict[str, Any]] = {}
    approval_last: dict[str, bool] = {}

    for e in events:
        ts = e.get("ts", "")
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        typ = e.get("type")
        payload = e.get("payload") or {}

        if typ == "run_started":
            workflow_name = str(payload.get("workflow_name", ""))
            workflow_version = str(payload.get("workflow_version", ""))
            tags = payload.get("tags") or {}
            run_metadata = payload.get("run_metadata") or {}
        elif typ == "state_entered":
            states.append({"state": str(payload.get("state", "")), "ts": ts})
        elif typ == "structured_output":
            outputs.append({"schema_name": payload.get("schema_name", ""), "data": payload.get("data")})
        elif typ == "tool_call":
            tool_calls.append({
                "tool": payload.get("name", ""), "seq": e.get("seq", ""), "args": payload.get("arguments"),
            })
        elif typ == "tool_result":
            tool_calls.append({
                "tool": payload.get("name", "result"),
                "seq": e.get("seq", ""),
                "args": payload.get("result"),
            })
        elif typ == "llm_response":
            usage = payload.get("usage") or {}
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            tt = usage.get("total_tokens")
            if isinstance(pt, int):
                prompt_tokens += pt
            if isinstance(ct, int):
                completion_tokens += ct
            if isinstance(tt, int):
                total_tokens += tt
        elif typ == "run_completed":
            status = str(payload.get("status", status))
        elif typ == "run_paused":
            status = "paused"
        elif typ == "run_failed":
            status = "failed"
        elif typ == "approval_requested":
            aid = payload.get("approval_id")
            if aid is not None:
                approval_requests[str(aid)] = {
                    "summary": payload.get("summary", ""),
                    "state": payload.get("state", ""),
                }
        elif typ == "approval_resolved":
            aid = payload.get("approval_id")
            if aid is not None:
                approval_last[str(aid)] = bool(payload.get("approved"))

    duration = "n/a"
    t0 = _parse_iso_ts(first_ts)
    t1 = _parse_iso_ts(last_ts)
    if t0 and t1:
        delta = t1 - t0
        secs = delta.total_seconds()
        if secs < 60:
            duration = f"{secs:.1f}s"
        else:
            duration = f"{secs / 60:.1f}m"

    status_classes = {
        "completed": "rp-badge-ok",
        "failed": "rp-badge-err",
        "paused": "rp-badge-pause",
    }
    status_class = status_classes.get(status, "rp-badge-neutral")

    tags_html = ""
    if tags:
        tag_strs = ", ".join(f"{html.escape(k)}={html.escape(v)}" for k, v in tags.items())
        tags_html = f'<p><span class="rp-label">Tags:</span> {tag_strs}</p>'
    meta_html = ""
    if run_metadata:
        meta_html = (
            '<p><span class="rp-label">Run metadata:</span> '
            f'<code class="rp-code">{html.escape(json.dumps(run_metadata, default=str)[:4000])}</code></p>'
        )

    timeline_items = []
    for s in states:
        dot_class = "rp-dot-muted"
        if s["state"] == states[-1]["state"] and status == "completed":
            dot_class = "rp-dot-ok"
        elif s["state"] == states[-1]["state"] and status == "failed":
            dot_class = "rp-dot-err"
        timeline_items.append(
            TIMELINE_ITEM.format(state=html.escape(s["state"]), ts=html.escape(s["ts"]), dot_class=dot_class)
        )
    timeline_html = (
        "\n".join(timeline_items)
        if timeline_items
        else '<li class="rp-tl-item"><p class="rp-muted">No states recorded</p></li>'
    )

    outputs_section = ""
    if outputs:
        items = []
        for o in outputs:
            items.append(
                OUTPUT_ITEM.format(
                    schema_name=html.escape(str(o["schema_name"])),
                    data_json=html.escape(json.dumps(o["data"], indent=2, default=str)),
                )
            )
        outputs_section = OUTPUTS_SECTION.format(items="\n".join(items))

    tool_calls_section = ""
    if tool_calls and style == "default":
        items = []
        for tc in tool_calls:
            items.append(
                TOOL_CALL_ITEM.format(
                    tool=html.escape(str(tc["tool"])),
                    seq=html.escape(str(tc["seq"])),
                    detail_json=html.escape(json.dumps(tc.get("args"), indent=2, default=str)),
                )
            )
        tool_calls_section = TOOL_CALLS_SECTION.format(items="\n".join(items))

    approvals_section = ""
    if approval_requests:
        items_a: list[str] = []
        for aid, meta in sorted(approval_requests.items()):
            if aid in approval_last:
                outcome = "Approved" if approval_last[aid] else "Rejected"
            else:
                outcome = "Pending (no resolution in this log)"
            items_a.append(
                APPROVAL_ITEM.format(
                    approval_id=html.escape(aid),
                    state=html.escape(str(meta.get("state", ""))),
                    summary=html.escape(str(meta.get("summary", ""))),
                    outcome=html.escape(outcome),
                )
            )
        approvals_section = APPROVALS_SECTION.format(items="\n".join(items_a))

    if style == "stakeholder":
        token_section = (
            '<section class="rp-section"><p class="rp-muted">Tool-call and token usage sections omitted. '
            "For the full technical report, run "
            f'<code class="rp-code">replayt report {html.escape(run_id)} --style default</code>'
            "</p></section>"
        )
        report_title = "Run summary"
    else:
        token_section = TOKEN_USAGE_SECTION.format(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        report_title = "Run Report"

    report = REPORT_HTML.format(
        report_title=html.escape(report_title),
        run_id=html.escape(run_id),
        workflow_name=html.escape(workflow_name),
        workflow_version=html.escape(workflow_version),
        status=html.escape(status),
        status_class=status_class,
        duration=html.escape(duration),
        tags_html=tags_html,
        meta_html=meta_html,
        approvals_section=approvals_section,
        timeline_html=timeline_html,
        outputs_section=outputs_section,
        tool_calls_section=tool_calls_section,
        token_section=token_section,
    )

    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        typer.echo(f"Wrote report to {out_path}")
    else:
        typer.echo(report)


@app.command("report-diff")
def cmd_report_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(Path(".replayt/runs"), "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Write HTML here (default: stdout)."),
) -> None:
    """HTML side-by-side comparison of two runs from local JSONL (no model calls)."""

    from replayt.cli.report_template import build_report_diff_html, collect_report_context

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    with _read_store(log_dir, sqlite) as store:
        events_a = store.load_events(run_a)
        events_b = store.load_events(run_b)
    if not events_a:
        typer.echo(f"No events for run_id={run_a!r}", err=True)
        raise typer.Exit(code=2)
    if not events_b:
        typer.echo(f"No events for run_id={run_b!r}", err=True)
        raise typer.Exit(code=2)
    ctx_a = collect_report_context(events_a)
    ctx_b = collect_report_context(events_b)
    doc = build_report_diff_html(run_a, run_b, ctx_a, ctx_b)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(doc, encoding="utf-8")
        typer.echo(f"Wrote {out_path}")
    else:
        typer.echo(doc)


@app.command("export-run")
def cmd_export_run(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", help="Output path (.tar.gz)."),
    log_dir: Path = typer.Option(Path(".replayt/runs"), "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    export_mode: str = typer.Option(
        "redacted",
        "--export-mode",
        case_sensitive=False,
        help="Sanitize copy: redacted | full | structured_only",
    ),
) -> None:
    """Write a shareable .tar.gz: sanitized events.jsonl + manifest.json."""

    log_dir = _resolve_log_dir(log_dir, log_subdir)
    lm = _parse_log_mode(export_mode)
    with _read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    lines = events_to_jsonl_lines(events, lm)
    bundle = b"".join(lines)
    digest = hashlib.sha256(bundle).hexdigest()
    manifest: dict[str, Any] = {
        "schema": "replayt.export_bundle.v1",
        "run_id": run_id,
        "export_mode": export_mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(lines),
        "events_jsonl_sha256": digest,
        "note": "Sanitized copy for sharing; not necessarily byte-identical to on-disk JSONL.",
    }
    man_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tf:
        ti = tarfile.TarInfo(name=f"{run_id}/events.jsonl")
        ti.size = len(bundle)
        tf.addfile(ti, io.BytesIO(bundle))
        ti2 = tarfile.TarInfo(name=f"{run_id}/manifest.json")
        ti2.size = len(man_bytes)
        tf.addfile(ti2, io.BytesIO(man_bytes))
    typer.echo(f"wrote {out.resolve()} ({len(lines)} events, sha256={digest[:16]}...)")


@app.command("log-schema")
def cmd_log_schema() -> None:
    """Print the bundled JSON Schema for one JSONL event object (stdout, machine-readable)."""

    path = importlib.resources.files("replayt").joinpath("schemas/run_log_event_line.schema.json")
    typer.echo(path.read_text(encoding="utf-8"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
