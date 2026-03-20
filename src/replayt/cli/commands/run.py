"""Commands: init, run, try, ci, resume."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.cli.ci_artifacts import (
    resolve_ci_junit_path,
    should_write_github_step_summary,
    write_ci_artifacts,
)
from replayt.cli.config import (
    DEFAULT_LOG_DIR,
    get_project_config,
    parse_log_mode,
    resolve_log_dir,
    resolve_strict_mirror,
    resume_hook_timeout_seconds,
)
from replayt.cli.constants import INIT_ENV_EXAMPLE, INIT_GITHUB_REPLAYT_WORKFLOW, INIT_GITIGNORE_LINES
from replayt.cli.run_support import (
    build_internal_run_argv,
    dry_check_suggested_command,
    exit_for_run_result,
    invoke_resume_hook,
    resume_hook_argv,
    run_result_payload,
    subprocess_env_child,
)
from replayt.cli.stores import make_store
from replayt.cli.targets import load_target
from replayt.cli.validation import (
    inputs_json_from_options,
    validate_workflow_graph,
    validation_report,
)
from replayt.persistence import MultiStore
from replayt.runner import Runner, resolve_approval_on_store


def merge_gitignore(directory: Path) -> None:
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


def cmd_init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Directory to write scaffold files into."),
    force: bool = typer.Option(False, help="Overwrite existing workflow.py / .env.example."),
    template: str = typer.Option("basic", "--template", "-t", help="basic|approval|tool-using|yaml"),
    ci: str | None = typer.Option(
        None,
        "--ci",
        help="Also write CI workflow: github → .github/workflows/replayt.yml (replace CHANGE_ME_MODULE:wf).",
    ),
) -> None:
    """Create a minimal workflow file and .env.example in the given directory."""

    from replayt.cli.templates import TEMPLATES

    if template not in TEMPLATES:
        raise typer.BadParameter(f"Unknown template {template!r}; choose from: {', '.join(sorted(TEMPLATES))}")
    if ci is not None and ci.strip().lower() != "github":
        raise typer.BadParameter("--ci must be github (or omit)")

    content, filename = TEMPLATES[template]
    path.mkdir(parents=True, exist_ok=True)
    wf_file = path / filename
    env_file = path / ".env.example"
    gh_workflow = path / ".github" / "workflows" / "replayt.yml"
    if not force:
        conflicts = [p for p in (wf_file, env_file) if p.exists()]
        if ci and gh_workflow.is_file():
            conflicts.append(gh_workflow)
        if conflicts:
            typer.echo(
                "Refusing to overwrite (use --force): " + ", ".join(str(p) for p in conflicts),
                err=True,
            )
            raise typer.Exit(code=1)
    wf_file.write_text(content, encoding="utf-8")
    env_file.write_text(INIT_ENV_EXAMPLE, encoding="utf-8")
    merge_gitignore(path)
    typer.echo(f"Wrote {wf_file} (template={template})")
    typer.echo(f"Wrote {env_file}")
    if ci:
        gh_workflow.parent.mkdir(parents=True, exist_ok=True)
        gh_workflow.write_text(INIT_GITHUB_REPLAYT_WORKFLOW, encoding="utf-8")
        typer.echo(f"Wrote {gh_workflow} (edit CHANGE_ME_MODULE:wf)")
    typer.echo("Next steps:")
    typer.echo("  1) python -m venv .venv && activate   # then: pip install replayt")
    typer.echo("  2) replayt doctor                     # see docs/QUICKSTART.md if anything is WARN")
    typer.echo("  3) replayt try                         # packaged tutorial, offline by default (--live for LLM)")
    typer.echo(f"  4) replayt run {wf_file} --dry-check # validate graph without executing")
    typer.echo(f"  5) replayt run {wf_file} --inputs-json '{{}}'  # or: --inputs-file inputs.json")
    typer.echo("  6) replayt inspect <run_id> && replayt replay <run_id>   # after step 5, copy run_id from output")


def cmd_run(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR, workflow.py, or workflow.yaml. "
            "Loading a .py file executes that file as code—use only trusted paths."
        ),
    ),
    run_id: str | None = typer.Option(None, help="Optional run id (default: random UUID)."),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help="Optional JSON object merged into the run context.",
    ),
    inputs_file: Path | None = typer.Option(
        None,
        "--inputs-file",
        help="Read inputs JSON object from this file (mutually exclusive with --inputs-json).",
    ),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, help="Directory for JSONL run logs."),
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
    experiment_json: str | None = typer.Option(
        None,
        "--experiment-json",
        help="JSON object on run_started as experiment and merged into LLM effective settings for the run.",
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
    strict_graph: bool = typer.Option(
        False,
        "--strict-graph",
        help="Require declared transitions when the workflow has 2+ states (note_transition or YAML-inferred edges).",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--output",
        "-o",
        help="text (default) or json (machine-readable).",
    ),
    replayt_internal_junit_xml: Path | None = typer.Option(
        None,
        "--replayt-internal-junit-xml",
        hidden=True,
        help="Set by replayt ci --junit-xml (not a public API).",
    ),
    replayt_internal_github_summary: bool = typer.Option(
        False,
        "--replayt-internal-github-summary",
        hidden=True,
        help="Set by replayt ci --github-summary (not a public API).",
    ),
) -> None:
    if resume and not run_id:
        typer.echo("When using --resume, you must pass --run-id", err=True)
        raise typer.Exit(code=2)

    inputs_resolved = inputs_json_from_options(inputs_json, inputs_file)

    in_child = os.environ.get("REPLAYT_SUBPROCESS_RUN") == "1"
    cfg, _ = get_project_config()
    log_dir = resolve_log_dir(log_dir, log_subdir)
    if sqlite is None and cfg.get("sqlite"):
        sqlite = Path(cfg["sqlite"])
    strict_mirror = resolve_strict_mirror(cfg, sqlite=sqlite)
    if log_mode == "redacted" and cfg.get("log_mode"):
        log_mode = cfg["log_mode"]
    if not in_child and timeout is None and cfg.get("timeout"):
        timeout = int(cfg["timeout"])
    if in_child:
        timeout = None

    wf = load_target(target)

    if dry_check:
        if resume:
            typer.echo("--dry-check cannot be used with --resume", err=True)
            raise typer.Exit(code=2)
        errors, warnings = validate_workflow_graph(wf, strict_graph=strict_graph)
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
        typer.echo(f"OK: {wf.name}@{wf.version} (dry check passed; no run executed)")
        typer.echo(
            "Next: "
            + dry_check_suggested_command(
                target=target,
                inputs_json=inputs_resolved,
                log_dir=log_dir,
                sqlite=sqlite,
                log_mode=log_mode,
                tag=tag,
                dry_run=dry_run,
            )
        )
        return

    errors, warnings = validate_workflow_graph(wf, strict_graph=strict_graph)
    for w in warnings:
        typer.echo(f"Warning: {w}", err=True)
    if errors:
        typer.echo(f"INVALID: {wf.name}@{wf.version}", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)

    junit_for_ci = resolve_ci_junit_path(replayt_internal_junit_xml)
    github_summary_for_ci = should_write_github_step_summary(replayt_internal_github_summary)

    if not in_child and timeout is not None and timeout > 0:
        argv = build_internal_run_argv(
            target=target,
            run_id=run_id,
            inputs_json=inputs_resolved,
            log_dir=log_dir,
            sqlite=sqlite,
            log_mode=log_mode,
            tag=tag,
            resume=resume,
            dry_run=dry_run,
            output=output,
            metadata_json=metadata_json,
            experiment_json=experiment_json,
            strict_graph=strict_graph,
            replayt_internal_junit_xml=junit_for_ci,
            replayt_internal_github_summary=github_summary_for_ci,
        )
        env = subprocess_env_child()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "replayt.cli.main", *argv],
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            typer.echo(f"Run timed out after {timeout}s", err=True)
            if run_id is not None:
                try:
                    store = make_store(log_dir, sqlite, strict_mirror=strict_mirror)
                    try:
                        note = (
                            "Parent subprocess timeout; event appended via same store layout as the run "
                            "(including SQLite mirror when configured)."
                            if sqlite is not None
                            else "Parent subprocess timeout; JSONL only (no --sqlite)."
                        )
                        store.append_event(
                            run_id,
                            ts=datetime.now(timezone.utc).isoformat(),
                            typ="run_interrupted",
                            payload={
                                "reason": "subprocess_timeout",
                                "timeout_seconds": timeout,
                                "note": note,
                            },
                        )
                    finally:
                        if isinstance(store, MultiStore):
                            store.close()
                except Exception:
                    pass
            raise typer.Exit(code=1)
        rc = completed.returncode if completed.returncode is not None else 1
        raise typer.Exit(code=rc)

    inputs: dict[str, Any] | None = None
    if inputs_resolved is not None:
        inputs = json.loads(inputs_resolved)
        if not isinstance(inputs, dict):
            raise typer.BadParameter("inputs must be a JSON object")
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
    experiment: dict[str, Any] | None = None
    if experiment_json is not None:
        parsed_e = json.loads(experiment_json)
        if not isinstance(parsed_e, dict):
            raise typer.BadParameter("--experiment-json must be a JSON object")
        try:
            json.dumps(parsed_e)
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter("--experiment-json must be JSON-serializable") from exc
        experiment = parsed_e
    lm = parse_log_mode(log_mode)
    store = make_store(log_dir, sqlite, strict_mirror=strict_mirror)
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
            experiment=experiment,
        )
    except KeyboardInterrupt:
        raise typer.Exit(code=1)
    finally:
        runner.close()
    if output == "json":
        typer.echo(json.dumps(run_result_payload(wf, result), indent=2, default=str))
    else:
        typer.echo(f"run_id={result.run_id}")
        typer.echo(f"workflow={wf.name}@{wf.version}")
        typer.echo(f"status={result.status}")
        if result.error:
            typer.echo(f"error={result.error}")
    write_ci_artifacts(
        wf,
        result,
        junit_path=junit_for_ci,
        github_summary=github_summary_for_ci,
    )
    exit_for_run_result(result)


def cmd_try(
    ctx: typer.Context,
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, help="Directory for JSONL run logs."),
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
    live: bool = typer.Option(
        False,
        "--live",
        help="Call the real LLM (needs OPENAI_API_KEY). Default is offline placeholder responses.",
    ),
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
        inputs_file=None,
        log_dir=log_dir,
        log_subdir=None,
        sqlite=sqlite,
        log_mode=log_mode,
        tag=tag,
        metadata_json=None,
        experiment_json=None,
        resume=False,
        timeout=timeout,
        dry_run=not live,
        dry_check=dry_check,
        strict_graph=False,
        output=output,
        replayt_internal_junit_xml=None,
        replayt_internal_github_summary=False,
    )


def cmd_ci(
    ctx: typer.Context,
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR, workflow.py, or workflow.yaml. "
            "Loading a .py file executes that file as code—use only trusted paths."
        ),
    ),
    run_id: str | None = typer.Option(None, help="Optional run id (default: random UUID)."),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help="Optional JSON object merged into the run context.",
    ),
    inputs_file: Path | None = typer.Option(
        None,
        "--inputs-file",
        help="Read inputs JSON object from this file (mutually exclusive with --inputs-json).",
    ),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, help="Directory for JSONL run logs."),
    sqlite: Path | None = typer.Option(None, help="Optional SQLite file mirrored alongside JSONL."),
    log_mode: str = typer.Option(
        "redacted",
        case_sensitive=False,
        help="redacted|full|structured_only",
    ),
    tag: list[str] | None = typer.Option(None, "--tag", help="Tag as key=value (repeatable)."),
    metadata_json: str | None = typer.Option(
        None,
        "--metadata-json",
        help="JSON object on run_started as run_metadata.",
    ),
    experiment_json: str | None = typer.Option(
        None,
        "--experiment-json",
        help="JSON object on run_started as experiment (merged into LLM effective settings).",
    ),
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
        help="Validate workflow graph and inputs JSON only; no run, no LLM.",
    ),
    strict_graph: bool = typer.Option(
        False,
        "--strict-graph",
        help="Require declared transitions when the workflow has 2+ states.",
    ),
    junit_xml: Path | None = typer.Option(
        None,
        "--junit-xml",
        help="Write a minimal JUnit XML file for this run (completed / failed / paused).",
    ),
    github_summary: bool = typer.Option(
        False,
        "--github-summary",
        help="Append a markdown summary to GITHUB_STEP_SUMMARY when that env var is set.",
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
        inputs_file=inputs_file,
        log_dir=log_dir,
        log_subdir=None,
        sqlite=sqlite,
        log_mode=log_mode,
        tag=tag,
        metadata_json=metadata_json,
        experiment_json=experiment_json,
        resume=resume,
        timeout=timeout,
        dry_run=dry_run,
        dry_check=dry_check,
        strict_graph=strict_graph,
        output=output,
        replayt_internal_junit_xml=junit_xml,
        replayt_internal_github_summary=github_summary,
    )


def cmd_resume(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "MODULE:VAR or workflow file (same as ``replayt run``). "
            "``.py`` paths execute code—use only trusted paths."
        ),
    ),
    run_id: str = typer.Argument(...),
    approval_id: str = typer.Option(..., "--approval", help="Approval id to resolve."),
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve."),
    resolver: str = typer.Option("cli", "--resolver", help="Stored on approval_resolved (default cli)."),
    reason: str | None = typer.Option(None, "--reason", help="Optional audit note on approval_resolved."),
    actor_json: str | None = typer.Option(
        None,
        "--actor-json",
        help="Optional JSON object stored as approval_resolved.actor (e.g. email, ticket id).",
    ),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None),
    log_mode: str = typer.Option("redacted", case_sensitive=False),
) -> None:
    cfg, _ = get_project_config()
    if sqlite is None and cfg.get("sqlite"):
        sqlite = Path(cfg["sqlite"])
    strict_mirror = resolve_strict_mirror(cfg, sqlite=sqlite)
    log_dir = resolve_log_dir(log_dir, log_subdir)
    if log_mode == "redacted" and cfg.get("log_mode"):
        log_mode = cfg["log_mode"]
    wf = load_target(target)
    lm = parse_log_mode(log_mode)
    store = make_store(log_dir, sqlite, strict_mirror=strict_mirror)
    hook = resume_hook_argv(cfg)
    if hook:
        hook_timeout = resume_hook_timeout_seconds(cfg)
        try:
            invoke_resume_hook(
                hook,
                target=target,
                run_id=run_id,
                approval_id=approval_id,
                reject=reject,
                timeout_seconds=hook_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            lim = f"{hook_timeout}s" if hook_timeout is not None else "unlimited"
            typer.echo(
                f"resume_hook timed out (limit {lim}); set REPLAYT_RESUME_HOOK_TIMEOUT or "
                "resume_hook_timeout in project config (<=0 for no limit).",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        except subprocess.CalledProcessError as exc:
            typer.echo(f"resume_hook exited with code {exc.returncode}", err=True)
            raise typer.Exit(code=1) from exc
    actor: dict[str, Any] | None = None
    if actor_json is not None:
        parsed_a = json.loads(actor_json)
        if not isinstance(parsed_a, dict):
            raise typer.BadParameter("--actor-json must be a JSON object")
        json.dumps(parsed_a)
        actor = parsed_a
    resolve_approval_on_store(
        store,
        run_id,
        approval_id,
        approved=not reject,
        resolver=resolver,
        reason=reason,
        actor=actor,
    )
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
    exit_for_run_result(result)


def register(app: typer.Typer) -> None:
    app.command("init")(cmd_init)
    app.command("run")(cmd_run)
    app.command("try")(cmd_try)
    app.command("ci")(cmd_ci)
    app.command("resume")(cmd_resume)
