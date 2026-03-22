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

RUN_RESULT_SCHEMA = "replayt.run_result.v1"


def _workflow_contract_hook_env(contract: dict[str, Any]) -> dict[str, str]:
    """Env vars shared by run_hook and resume_hook for workflow-surface policy checks."""

    wf = contract.get("workflow") if isinstance(contract.get("workflow"), dict) else {}
    sha = contract.get("contract_sha256")
    return {
        "REPLAYT_WORKFLOW_CONTRACT_SHA256": str(sha) if sha is not None else "",
        "REPLAYT_WORKFLOW_NAME": str(wf.get("name", "")),
        "REPLAYT_WORKFLOW_VERSION": str(wf.get("version", "")),
    }


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


def _hook_source(cfg: dict[str, Any], *, env_var: str, config_key: str) -> str:
    env_hook = os.environ.get(env_var, "").strip()
    if env_hook:
        return f"env:{env_var}"
    if cfg.get(config_key):
        return f"project_config:{config_key}"
    return "unset"


def _hook_audit_payload(argv: list[str] | None, *, source: str) -> dict[str, Any] | None:
    if not argv:
        return None
    raw_argv0 = str(argv[0]).strip()
    argv0 = Path(raw_argv0).name or raw_argv0
    return {
        "source": source,
        "argv0": argv0,
        "arg_count": len(argv),
    }


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


def seal_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional pre-seal policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_SEAL_HOOK", config_key="seal_hook")


def verify_seal_hook_argv(cfg: dict[str, Any]) -> list[str] | None:
    """Argv for the optional post-verify policy subprocess (trusted project config / env only)."""

    return _hook_argv(cfg, env_var="REPLAYT_VERIFY_SEAL_HOOK", config_key="verify_seal_hook")


def run_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_RUN_HOOK", config_key="run_hook")


def resume_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_RESUME_HOOK", config_key="resume_hook")


def export_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_EXPORT_HOOK", config_key="export_hook")


def seal_hook_source(cfg: dict[str, Any]) -> str:
    return _hook_source(cfg, env_var="REPLAYT_SEAL_HOOK", config_key="seal_hook")


def run_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(run_hook_argv(cfg), source=run_hook_source(cfg))


def resume_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(resume_hook_argv(cfg), source=resume_hook_source(cfg))


def export_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(export_hook_argv(cfg), source=export_hook_source(cfg))


def seal_hook_audit(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return _hook_audit_payload(seal_hook_argv(cfg), source=seal_hook_source(cfg))


def invoke_hook(argv: list[str], *, extra_env: dict[str, str], timeout_seconds: float | None) -> None:
    """Run *argv* with extra env vars; *argv* must come from trusted config."""

    env = {**os.environ, **extra_env}
    subprocess.run(
        argv,
        env=env,
        check=True,
        timeout=timeout_seconds,
        stdin=subprocess.DEVNULL,
    )


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
    workflow_contract: dict[str, Any],
    inputs_json: str | None,
    tags_json: str | None,
    metadata_json: str | None,
    experiment_json: str | None,
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
        **_workflow_contract_hook_env(workflow_contract),
    }
    if sqlite is not None:
        extra_env["REPLAYT_SQLITE"] = str(sqlite.resolve())
    if inputs_json is not None:
        extra_env["REPLAYT_RUN_INPUTS_JSON"] = inputs_json
    if tags_json is not None:
        extra_env["REPLAYT_RUN_TAGS_JSON"] = tags_json
    if metadata_json is not None:
        extra_env["REPLAYT_RUN_METADATA_JSON"] = metadata_json
    if experiment_json is not None:
        extra_env["REPLAYT_RUN_EXPERIMENT_JSON"] = experiment_json
    invoke_hook(argv, extra_env=extra_env, timeout_seconds=timeout_seconds)


def invoke_resume_hook(
    argv: list[str],
    *,
    target: str,
    run_id: str,
    approval_id: str,
    reject: bool,
    workflow_contract: dict[str, Any],
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
            **_workflow_contract_hook_env(workflow_contract),
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
    workflow_contract: dict[str, Any],
    cli_target: str | None,
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
        **_workflow_contract_hook_env(workflow_contract),
    }
    if sqlite is not None:
        extra["REPLAYT_SQLITE"] = str(sqlite.resolve())
    if report_style is not None:
        extra["REPLAYT_BUNDLE_REPORT_STYLE"] = report_style
    if cli_target:
        extra["REPLAYT_TARGET"] = cli_target
    invoke_hook(argv, extra_env=extra, timeout_seconds=timeout_seconds)


def invoke_seal_hook(
    argv: list[str],
    *,
    run_id: str,
    log_dir: Path,
    jsonl_path: Path,
    seal_out: Path,
    line_count: int,
    workflow_contract: dict[str, Any],
    timeout_seconds: float | None,
) -> None:
    """Run *argv* before ``replayt seal`` writes the manifest; *argv* is trusted config only."""

    invoke_hook(
        argv,
        extra_env={
            "REPLAYT_RUN_ID": run_id,
            "REPLAYT_LOG_DIR": str(log_dir.resolve()),
            "REPLAYT_SEAL_JSONL": str(jsonl_path.resolve()),
            "REPLAYT_SEAL_OUT": str(seal_out.resolve()),
            "REPLAYT_SEAL_LINE_COUNT": str(line_count),
            **_workflow_contract_hook_env(workflow_contract),
        },
        timeout_seconds=timeout_seconds,
    )


def invoke_verify_seal_hook(
    argv: list[str],
    *,
    run_id: str,
    log_dir: Path,
    manifest_path: Path,
    jsonl_path: Path,
    manifest_schema: str,
    line_count: int,
    file_sha256: str,
    workflow_contract: dict[str, Any],
    timeout_seconds: float | None,
) -> None:
    """Run *argv* after ``replayt verify-seal`` digests match; *argv* is trusted config only."""

    invoke_hook(
        argv,
        extra_env={
            "REPLAYT_RUN_ID": run_id,
            "REPLAYT_LOG_DIR": str(log_dir.resolve()),
            "REPLAYT_VERIFY_SEAL_MANIFEST": str(manifest_path.resolve()),
            "REPLAYT_VERIFY_SEAL_JSONL": str(jsonl_path.resolve()),
            "REPLAYT_VERIFY_SEAL_SCHEMA": manifest_schema,
            "REPLAYT_VERIFY_SEAL_LINE_COUNT": str(line_count),
            "REPLAYT_VERIFY_SEAL_FILE_SHA256": file_sha256,
            **_workflow_contract_hook_env(workflow_contract),
        },
        timeout_seconds=timeout_seconds,
    )


def build_policy_hook_env_catalog() -> dict[str, Any]:
    """Stable machine-readable contract for trusted policy-hook subprocesses (CI / MCP wrappers)."""

    hooks: dict[str, dict[str, Any]] = {
        "run_hook": {
            "argv_env": "REPLAYT_RUN_HOOK",
            "argv_config_key": "run_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_DRY_RUN",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_LOG_MODE",
                    "REPLAYT_RUN_EXPERIMENT_JSON",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_RUN_INPUTS_JSON",
                    "REPLAYT_RUN_METADATA_JSON",
                    "REPLAYT_RUN_MODE",
                    "REPLAYT_RUN_TAGS_JSON",
                    "REPLAYT_SQLITE",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "resume_hook": {
            "argv_env": "REPLAYT_RESUME_HOOK",
            "argv_config_key": "resume_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_APPROVAL_ID",
                    "REPLAYT_REJECT",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "export_hook": {
            "argv_env": "REPLAYT_EXPORT_HOOK",
            "argv_config_key": "export_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_BUNDLE_REPORT_STYLE",
                    "REPLAYT_EXPORT_EVENT_COUNT",
                    "REPLAYT_EXPORT_KIND",
                    "REPLAYT_EXPORT_MODE",
                    "REPLAYT_EXPORT_OUT",
                    "REPLAYT_EXPORT_SEAL",
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_SQLITE",
                    "REPLAYT_TARGET",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "seal_hook": {
            "argv_env": "REPLAYT_SEAL_HOOK",
            "argv_config_key": "seal_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_SEAL_JSONL",
                    "REPLAYT_SEAL_LINE_COUNT",
                    "REPLAYT_SEAL_OUT",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
        "verify_seal_hook": {
            "argv_env": "REPLAYT_VERIFY_SEAL_HOOK",
            "argv_config_key": "verify_seal_hook",
            "injected_env_vars": sorted(
                {
                    "REPLAYT_LOG_DIR",
                    "REPLAYT_RUN_ID",
                    "REPLAYT_VERIFY_SEAL_FILE_SHA256",
                    "REPLAYT_VERIFY_SEAL_JSONL",
                    "REPLAYT_VERIFY_SEAL_LINE_COUNT",
                    "REPLAYT_VERIFY_SEAL_MANIFEST",
                    "REPLAYT_VERIFY_SEAL_SCHEMA",
                    "REPLAYT_WORKFLOW_CONTRACT_SHA256",
                    "REPLAYT_WORKFLOW_NAME",
                    "REPLAYT_WORKFLOW_VERSION",
                }
            ),
        },
    }
    return {
        "subprocess_stdin": "devnull",
        "hooks": {name: hooks[name] for name in sorted(hooks)},
    }


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


def build_cli_stdio_contract() -> dict[str, Any]:
    """When the CLI may read the parent process stdin (subprocess / MCP wrappers).

    Policy hooks always use ``stdin=subprocess.DEVNULL``; see ``policy_hook_env_catalog``.
    """

    return {
        "recommended_subprocess_stdin": "devnull",
        "reads_utf8_json_object_from_stdin": {
            "subcommands": sorted(["ci", "doctor", "run", "validate"]),
            "triggers": sorted(
                [
                    "cli:--inputs-file=-",
                    "cli:--inputs-json=@-",
                    "env:REPLAYT_INPUTS_FILE=-",
                ]
            ),
            "encoding": "utf-8",
            "empty_stdin_json": "object",
        },
        "note": (
            "Unless you intentionally forward a UTF-8 JSON object for one of the triggers above, pass "
            "stdin=subprocess.DEVNULL (or equivalent) so a host-attached stdin stream does not become "
            "the workflow inputs payload."
        ),
    }


def build_cli_exit_codes_report() -> dict[str, Any]:
    """Machine-readable exit semantics for CI wrappers (``replayt version --format json``)."""

    return {
        "workflow_run": {
            "subcommands": ["ci", "resume", "run", "try"],
            "exit_codes": {
                "0": {
                    "run_status": "completed",
                    "summary": "Workflow finished successfully.",
                },
                "1": {
                    "run_status": "failed",
                    "summary": (
                        "Workflow failed, was interrupted, or a precondition or policy hook aborted "
                        "(see stderr)."
                    ),
                },
                "2": {
                    "run_status": "paused",
                    "summary": "Paused for approval; continue with replayt resume.",
                },
            },
        },
        "json_health_gates": {
            "doctor": {"healthy_exit": 0, "unhealthy_exit": 1},
            "validate": {"ok_exit": 0, "not_ok_exit": 1},
        },
        "note": (
            "Listing, inspection, export, and seal helpers exit 1 on user or lookup errors so exit 2 "
            "stays reserved for paused workflow runs."
        ),
    }


def exit_for_run_result(result: RunResult) -> None:
    """Raise ``typer.Exit`` unless the run completed successfully."""

    code = exit_code_for_run_result(result)
    if code == 0:
        return
    raise typer.Exit(code=code)


def run_result_payload(wf: Workflow, result: RunResult) -> dict[str, Any]:
    return {
        "schema": RUN_RESULT_SCHEMA,
        "run_id": result.run_id,
        "workflow": f"{wf.name}@{wf.version}",
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
    }
