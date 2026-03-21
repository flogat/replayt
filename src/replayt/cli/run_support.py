"""Subprocess timeout wrapper, run/resume policy hooks, and run exit helpers."""

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
    redact_keys: list[str] | None,
    tag: list[str] | None,
    dry_run: bool,
) -> str:
    parts = ["replayt", "run", target, "--log-dir", str(log_dir), "--log-mode", log_mode]
    if sqlite is not None:
        parts.extend(["--sqlite", str(sqlite)])
    if redact_keys:
        for key in redact_keys:
            parts.extend(["--redact-key", key])
    if inputs_json is not None:
        parts.extend(["--inputs-json", inputs_json])
    if tag:
        for t in tag:
            parts.extend(["--tag", t])
    if dry_run:
        parts.append("--dry-run")
    return " ".join(parts)


def _hook_argv(cfg: dict[str, Any], *, env_var: str, config_key: str) -> list[str] | None:
    env_hook = os.environ.get(env_var, "").strip()
    use_posix = os.name != "nt"
    if env_hook:
        return shlex.split(env_hook, posix=use_posix)
    hook = cfg.get(config_key)
    if isinstance(hook, list) and hook and all(isinstance(x, str) for x in hook):
        return [str(x) for x in hook]
    if isinstance(hook, str) and hook.strip():
        return shlex.split(hook.strip(), posix=use_posix)
    return None


def run_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-run policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_RUN_HOOK", config_key="run_hook")


def resume_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional resume gate subprocess (trusted project config / env only).

    ``resume_hook`` and ``REPLAYT_RESUME_HOOK`` are split with ``shlex`` and executed
    without a shell, equivalent to typing the same argv in a terminal: do not point them
    at untrusted input.
    """

    return _hook_argv(cfg, env_var="REPLAYT_RESUME_HOOK", config_key="resume_hook")


def export_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-export policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_EXPORT_HOOK", config_key="export_hook")


def invoke_hook(argv: list[str], *, extra_env: dict[str, str], timeout_seconds: float | None) -> None:
    """Run *argv* with extra env vars; *argv* must come from trusted config."""

    env = {**os.environ, **extra_env}
    subprocess.run(argv, env=env, check=True, timeout=timeout_seconds)


def invoke_run_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    log_dir: Path,
    log_mode: str,
    dry_run: bool,
    resume: bool,
    sqlite: Path | None,
    timeout_seconds: float | None,
) -> None:
    """Run a pre-run policy hook before the workflow starts writing events."""

    extra_env = {
        "REPLAYT_TARGET": target,
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_RUN_MODE": "resume" if resume else "run",
        "REPLAYT_LOG_DIR": str(log_dir.resolve()),
        "REPLAYT_LOG_MODE": log_mode,
        "REPLAYT_DRY_RUN": "1" if dry_run else "0",
    }
    if sqlite is not None:
        extra_env["REPLAYT_SQLITE"] = str(sqlite.resolve())
    invoke_hook(argv, extra_env=extra_env, timeout_seconds=timeout_seconds)


def invoke_resume_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    approval_id: str,
    reject: bool,
    timeout_seconds: float | None,
) -> None:
    """Run *argv* with extra ``REPLAYT_*`` env vars; *argv* must come from trusted config."""

    invoke_hook(
        argv,
        extra_env={
            "REPLAYT_TARGET": target,
            "REPLAYT_RUN_ID": run_id,
            "REPLAYT_APPROVAL_ID": approval_id,
            "REPLAYT_REJECT": "1" if reject else "0",
        },
        timeout_seconds=timeout_seconds,
    )


def invoke_export_hook(
    argv: list[str],
    *,
    run_id: str,
    export_kind: str,
    log_dir: Path,
    sqlite: Path | None,
    export_mode: str,
    out: Path,
    seal: bool,
    event_count: int,
    report_style: str | None,
    timeout_seconds: float | None,
) -> None:
    """Run *argv* before ``export-run`` / ``bundle-export`` writes the archive; *argv* is trusted config only."""

    extra: dict[str, str] = {
        "REPLAYT_RUN_ID": run_id,
        "REPLAYT_EXPORT_KIND": export_kind,
        "REPLAYT_LOG_DIR": str(log_dir.resolve()),
        "REPLAYT_EXPORT_MODE": export_mode,
        "REPLAYT_EXPORT_OUT": str(out.resolve()),
        "REPLAYT_EXPORT_SEAL": "1" if seal else "0",
        "REPLAYT_EXPORT_EVENT_COUNT": str(event_count),
    }
    if sqlite is not None:
        extra["REPLAYT_SQLITE"] = str(sqlite.resolve())
    if report_style is not None:
        extra["REPLAYT_BUNDLE_REPORT_STYLE"] = report_style
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def build_internal_run_argv(
    *,
    target: str,
    run_id: str | None,
    inputs_json: str | None,
    log_dir: Path,
    sqlite: Path | None,
    log_mode: str,
    redact_keys: list[str] | None,
    tag: list[str] | None,
    resume: bool,
    dry_run: bool,
    output: str,
    metadata_json: str | None = None,
    experiment_json: str | None = None,
    strict_graph: bool = False,
    replayt_internal_junit_xml: Path | None = None,
    replayt_internal_github_summary: bool = False,
    replayt_internal_summary_json: Path | None = None,
) -> list[str]:
    """Argv for ``python -m replayt.cli.main`` (must not include ``--timeout``; parent enforces that)."""

    argv = ["run", target, "--log-dir", str(log_dir), "--log-mode", log_mode, "--output", output]
    if redact_keys:
        for key in redact_keys:
            argv += ["--redact-key", key]
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
    if replayt_internal_summary_json is not None:
        argv += ["--replayt-internal-summary-json", str(replayt_internal_summary_json.resolve())]
    return argv


def subprocess_env_child() -> dict[str, str]:
    """Environment for isolated ``replayt run`` children (timeout). Ensures ``replayt`` is importable."""

    env = {**os.environ, "REPLAYT_SUBPROCESS_RUN": "1"}
    for p in sys.path:
        if not p:
            continue
        try:
            root = Path(p)
            for candidate in (root, root / "src"):
                if Path(candidate, "replayt", "__init__.py").is_file():
                    prev = env.get("PYTHONPATH", "")
                    cand = str(candidate)
                    env["PYTHONPATH"] = f"{cand}{os.pathsep}{prev}" if prev else cand
                    return env
        except OSError:
            continue
    return env


def exit_code_for_run_result(result: RunResult) -> int:
    """CLI exit codes: 0 completed, 1 failed, 2 paused (waiting for approval or similar)."""

    if result.status == "completed":
        return 0
    if result.status == "paused":
        return 2
    return 1


def exit_for_run_result(result: RunResult) -> None:
    """Raise ``typer.Exit`` unless the run completed successfully."""

    code = exit_code_for_run_result(result)
    if code == 0:
        return
    raise typer.Exit(code=code)


def run_result_payload(wf: Workflow, result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "workflow": f"{wf.name}@{wf.version}",
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
    }
