"""Subprocess timeout wrapper, resume hooks, and run exit helpers."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer

from replayt.runner import RunResult
from replayt.workflow import Workflow


def dry_check_suggested_command(
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


def resume_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    env_hook = os.environ.get("REPLAYT_RESUME_HOOK", "").strip()
    use_posix = os.name != "nt"
    if env_hook:
        return shlex.split(env_hook, posix=use_posix)
    rh = cfg.get("resume_hook")
    if isinstance(rh, list) and rh and all(isinstance(x, str) for x in rh):
        return [str(x) for x in rh]
    if isinstance(rh, str) and rh.strip():
        return shlex.split(rh.strip(), posix=use_posix)
    return None


def invoke_resume_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    approval_id: str,
    reject: bool,
) -> None:
    env = {
        **os.environ,
        "REPLAYT_TARGET": target,
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_APPROVAL_ID": approval_id,
        "REPLAYT_REJECT": "1" if reject else "0",
    }
    subprocess.run(argv, env=env, check=True)


def build_internal_run_argv(
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
    experiment_json: str | None = None,
    strict_graph: bool = False,
    replayt_internal_junit_xml: Path | None = None,
    replayt_internal_github_summary: bool = False,
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
    if experiment_json is not None:
        argv += ["--experiment-json", experiment_json]
    if resume:
        argv.append("--resume")
    if dry_run:
        argv.append("--dry-run")
    if strict_graph:
        argv.append("--strict-graph")
    if replayt_internal_junit_xml is not None:
        argv += ["--replayt-internal-junit-xml", str(replayt_internal_junit_xml.resolve())]
    if replayt_internal_github_summary:
        argv.append("--replayt-internal-github-summary")
    return argv


def subprocess_env_child() -> dict[str, str]:
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


def exit_for_run_result(result: RunResult) -> None:
    """CLI exit codes: 0 completed, 1 failed, 2 paused (waiting for approval or similar)."""

    if result.status == "completed":
        return
    if result.status == "paused":
        raise typer.Exit(code=2)
    raise typer.Exit(code=1)


def run_result_payload(wf: Workflow, result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "workflow": f"{wf.name}@{wf.version}",
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
    }
