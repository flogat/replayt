"""Command: doctor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

import typer

from replayt.cli.ci_artifacts import ci_artifacts_payload, resolve_ci_artifacts
from replayt.cli.config import (
    DEFAULT_LOG_DIR,
    get_project_config,
    min_replayt_version_report,
    resolve_approval_reason_required,
    resolve_llm_settings,
    resolve_log_dir,
    resolve_log_mode_setting,
    resolve_run_inputs_json,
    resolve_sqlite_path,
)
from replayt.cli.path_readiness import ci_artifact_readiness_checks, readiness_checks
from replayt.cli.run_support import export_hook_audit, resume_hook_audit, run_hook_audit, seal_hook_audit
from replayt.cli.targets import load_target
from replayt.cli.validation import validate_workflow_graph, validation_report
from replayt.security import (
    dotenv_permission_trust_checks,
    dotenv_trust_candidate_paths,
    extraneous_llm_credential_env_names,
    llm_credential_env_presence,
    log_directory_permission_trust_checks,
    trust_boundary_checks,
)


def cmd_doctor(
    skip_connectivity: bool = typer.Option(
        False,
        "--skip-connectivity",
        help="Do not HTTP GET OPENAI_BASE_URL/models (no network; use when base URL is sensitive or untrusted).",
    ),
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (default) or json (machine-readable; exit 1 unless healthy - see docs/CLI.md).",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Optional workflow target to preflight-load and validate without executing.",
    ),
    inputs_json: str | None = typer.Option(
        None,
        "--inputs-json",
        help="Optional JSON object for --target preflight (same parse rules as replayt validate).",
    ),
    inputs_file: Path | None = typer.Option(
        None,
        "--inputs-file",
        help="Optional JSON file for --target preflight (same parse rules as replayt validate).",
    ),
    input_value: list[str] | None = typer.Option(
        None,
        "--input",
        help=(
            "Repeatable key=value input override for --target preflight. Dotted keys build nested objects "
            "(for example issue.title=Crash)."
        ),
    ),
    strict_graph: bool = typer.Option(
        False,
        "--strict-graph",
        help="Require declared transitions when validating an optional --target.",
    ),
) -> None:
    """Check local install health for replayt's default OpenAI-compatible setup.

    Without ``--skip-connectivity``, this command sends a request to ``OPENAI_BASE_URL`` (see README
    security notes): the URL and optional API key come from your environment. Only use connectivity
    checks against hosts you trust.
    """

    try:
        import replayt as _rt

        pkg_ver = getattr(_rt, "__version__", "unknown")
    except ImportError:
        pkg_ver = "unknown"

    cfg, cfg_path, unknown_cfg_keys = get_project_config()
    settings, llm_report = resolve_llm_settings(cfg)
    settings_error = llm_report.get("error")
    resolved_log_mode, _log_mode_source = resolve_log_mode_setting("redacted", cfg)
    resolved_log_dir = resolve_log_dir(DEFAULT_LOG_DIR)
    resolved_sqlite, _sqlite_source = resolve_sqlite_path(None, cfg, config_path=cfg_path)
    required_reason, required_reason_source = resolve_approval_reason_required(False, cfg)
    ci_artifacts = resolve_ci_artifacts(
        explicit_junit_xml=None,
        explicit_summary_json=None,
        explicit_github_summary=False,
    )

    checks: list[tuple[str, bool, str]] = []
    checks.append(("replayt", True, pkg_ver))
    if cfg_path:
        checks.append(("project_config", True, cfg_path))
    else:
        checks.append(("project_config", False, "No project config found"))
    if unknown_cfg_keys:
        checks.append(
            (
                "project_config_unknown_keys",
                False,
                "ignored: " + ", ".join(sorted(unknown_cfg_keys)),
            )
        )
    else:
        checks.append(("project_config_unknown_keys", True, "none"))

    mv = min_replayt_version_report(cfg, installed=pkg_ver)
    if mv["constraint"] is None:
        checks.append(("project_config_min_replayt_version", True, "unset"))
    elif mv["parse_error"]:
        checks.append(
            (
                "project_config_min_replayt_version",
                False,
                f"invalid constraint {mv['constraint']!r}: {mv['parse_error']}",
            )
        )
    elif not mv["satisfied"]:
        checks.append(
            (
                "project_config_min_replayt_version",
                False,
                f"need>={mv['constraint']}, installed {mv['installed']}",
            )
        )
    else:
        checks.append(
            (
                "project_config_min_replayt_version",
                True,
                f">={mv['constraint']} (installed {mv['installed']})",
            )
        )

    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("python", True, pyver))
    checks.append(
        (
            "replayt_provider",
            True,
            f"{llm_report['provider']} ({llm_report['provider_source']})",
        )
    )

    checks.append(
        (
            "openai_api_key",
            bool(llm_report["api_key_present"]),
            "set" if llm_report["api_key_present"] else "missing",
        )
    )
    extra_cred_env = extraneous_llm_credential_env_names()
    if extra_cred_env:
        checks.append(
            (
                "credential_env_extra_providers",
                False,
                "non-empty env (not read by replayt's OpenAI-compat client): " + ", ".join(extra_cred_env),
            )
        )
    else:
        checks.append(
            (
                "credential_env_extra_providers",
                True,
                "no extra provider credential env vars (see credential_env in JSON for full name/presence map)",
            )
        )
    if settings_error is None and settings is not None:
        checks.append(("openai_base_url", True, f"{llm_report['base_url']} ({llm_report['base_url_source']})"))
        checks.append(("model", True, f"{settings.model} ({llm_report['model_source']})"))
    else:
        checks.append(("provider_config", False, settings_error or "Invalid provider configuration"))
        checks.append(("openai_base_url", "base_url" in llm_report, llm_report.get("base_url") or "missing"))
        checks.append(("model", "model" in llm_report, llm_report.get("model") or "(provider default unavailable)"))

    try:
        import yaml  # type: ignore[import-not-found]

        _ = yaml
        checks.append(("yaml_extra", True, "installed"))
    except ImportError:
        checks.append(("yaml_extra", False, "missing (pip install replayt[yaml])"))

    if settings_error is not None:
        checks.append(("provider_connectivity", False, "skipped (invalid provider config)"))
    elif skip_connectivity:
        checks.append(("provider_connectivity", True, "skipped (--skip-connectivity)"))
    else:
        if settings is None:
            checks.append(("provider_connectivity", False, "skipped (no resolved LLM settings)"))
        else:
            try:
                import httpx

                with httpx.Client(timeout=5.0) as http_client:
                    headers: dict[str, str] = {}
                    if settings.api_key:
                        headers["Authorization"] = f"Bearer {settings.api_key}"
                    r = http_client.get(settings.base_url.rstrip("/") + "/models", headers=headers)
                reachable = r.status_code < 500
                detail = f"HTTP {r.status_code}"
                if r.status_code == 404:
                    detail += " (/models not implemented - try a chat request)"
                connectivity_detail = detail if reachable else f"{detail} (server error)"
                checks.append(("provider_connectivity", reachable, connectivity_detail))
            except Exception as exc:  # noqa: BLE001
                checks.append(("provider_connectivity", False, str(exc)))

    trust_base_url = settings.base_url if settings is not None else os.environ.get("OPENAI_BASE_URL")
    for check in trust_boundary_checks(base_url=trust_base_url, log_mode=resolved_log_mode):
        checks.append((check.name, check.ok, check.detail))
    if required_reason:
        checks.append(
            (
                "approval_reason_policy",
                True,
                f"approval_resolved.reason is required on replayt resume ({required_reason_source})",
            )
        )
    else:
        checks.append(
            (
                "approval_reason_policy",
                False,
                "approval_resolved.reason is optional; paused runs can be resumed without written justification",
            )
        )
    configured_policy_hooks = [
        (name, audit)
        for name, audit in (
            ("run_hook", run_hook_audit(cfg)),
            ("resume_hook", resume_hook_audit(cfg)),
            ("export_hook", export_hook_audit(cfg)),
            ("seal_hook", seal_hook_audit(cfg)),
        )
        if audit is not None
    ]
    if configured_policy_hooks:
        detail = ", ".join(f"{name}={audit['argv0']}" for name, audit in configured_policy_hooks)
        checks.append(
            (
                "policy_hooks_external_code",
                False,
                "trusted subprocess policy hooks enabled: " + detail,
            )
        )
    else:
        checks.append(("policy_hooks_external_code", True, "none"))
    for check in log_directory_permission_trust_checks(resolved_log_dir):
        checks.append((check.name, check.ok, check.detail))
    for check in dotenv_permission_trust_checks(
        dotenv_trust_candidate_paths(cwd=Path.cwd(), project_config_path=cfg_path)
    ):
        checks.append((check.name, check.ok, check.detail))
    for check in readiness_checks(log_dir=resolved_log_dir, sqlite=resolved_sqlite):
        checks.append((check.name, check.ok, check.detail))
    for check in ci_artifact_readiness_checks(
        junit_xml=ci_artifacts.junit_xml,
        summary_json=ci_artifacts.summary_json,
        github_summary_requested=ci_artifacts.github_summary_requested,
        github_step_summary=ci_artifacts.github_step_summary,
    ):
        checks.append((check.name, check.ok, check.detail))

    target_payload: dict[str, object] | None = None
    if target is not None:
        try:
            inputs_resolved, _inputs_src = resolve_run_inputs_json(
                inputs_json, inputs_file, cfg=cfg, config_path=cfg_path, input_value=input_value
            )
            wf = load_target(target)
            errors, warnings = validate_workflow_graph(wf, strict_graph=strict_graph)
            report = validation_report(
                target=target,
                wf=wf,
                strict_graph=strict_graph,
                errors=errors,
                warnings=warnings,
                inputs_json=inputs_resolved,
                metadata_json=None,
                experiment_json=None,
            )
            target_payload = report
            checks.append(
                (
                    "target_validation",
                    bool(report["ok"]),
                    (
                        f"{wf.name}@{wf.version} "
                        f"(states={report['workflow']['state_count']} edges={report['workflow']['edge_count']})"
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            target_payload = {"target": target, "ok": False, "errors": [str(exc)]}
            checks.append(("target_validation", False, str(exc)))

    hints = {
        "openai_api_key": "export OPENAI_API_KEY=... (see docs/QUICKSTART.md)",
        "yaml_extra": "pip install 'replayt[yaml]' for .yaml workflow targets",
        "project_config": "optional [tool.replayt] - docs/CONFIG.md",
        "project_config_unknown_keys": (
            "Remove or rename keys to match docs/CONFIG.md; run `replayt config --format json` "
            "and inspect project_config.unknown_keys."
        ),
        "project_config_min_replayt_version": (
            "Set min_replayt_version to a replayt-style release (e.g. 0.4.7), upgrade the installed "
            "package, or remove the key; run `replayt config --format json` for details."
        ),
        "provider_config": "set OPENAI_BASE_URL to an OpenAI-compatible gateway or use a supported preset",
        "provider_connectivity": "try replayt doctor --skip-connectivity; check OPENAI_BASE_URL",
        "trust_log_mode": "Prefer redacted or structured_only for logs that may contain sensitive text.",
        "trust_base_url_transport": "Use HTTPS for remote providers; keep plain HTTP for localhost-only gateways.",
        "trust_base_url_credentials": "Move secrets out of OPENAI_BASE_URL and into headers or env vars.",
        "credential_env_extra_providers": (
            "replayt does not load these vendor env vars; unset them in this shell or document why they "
            "remain for other tools—see README security notes and credential_env in doctor JSON."
        ),
        "trust_log_dir_other_readable": (
            "Tighten log_dir permissions so other OS accounts cannot read JSONL audit files."
        ),
        "trust_log_dir_other_writable": (
            "Tighten log_dir permissions so other OS accounts cannot append or replace run logs."
        ),
        "trust_dotenv_other_readable": (
            "Restrict .env permissions (for example chmod 600) so API keys are not readable by other OS accounts."
        ),
        "trust_dotenv_other_writable": (
            "Remove world-writable bits from .env so other accounts cannot swap in attacker-controlled secrets."
        ),
        "log_dir_ready": "Fix the resolved log_dir path or its parent-directory permissions before running replayt.",
        "sqlite_ready": "Fix the resolved sqlite path or its parent-directory permissions before enabling the mirror.",
        "ci_junit_xml_ready": (
            "Fix REPLAYT_JUNIT_XML (or pass --junit-xml) so the parent directory exists and is writable."
        ),
        "ci_summary_json_ready": (
            "Fix REPLAYT_SUMMARY_JSON (or pass --summary-json) so the parent directory exists and is writable."
        ),
        "ci_github_summary_ready": (
            "If you set REPLAYT_GITHUB_SUMMARY=1, make sure GITHUB_STEP_SUMMARY is exported by the CI runner."
        ),
        "target_validation": (
            "Use replayt validate TARGET or replayt doctor --target TARGET --strict-graph "
            "to inspect the preflight errors."
        ),
        "approval_reason_policy": (
            "Set approval_reason_required = true in project config or pass --require-reason on replayt resume "
            "when approval decisions need a written audit note."
        ),
        "policy_hooks_external_code": (
            "Prefer typed in-process hooks or outer wrappers when possible. If you keep CLI policy hooks, "
            "treat them as trusted local code and audit the compact breadcrumbs recorded in run_started.runtime, "
            "approval_resolved, and export/seal manifests."
        ),
    }
    if output == "json":
        soft = {
            "openai_api_key",
            "project_config",
            "project_config_unknown_keys",
            "yaml_extra",
            "trust_log_mode",
            "trust_base_url_transport",
            "trust_base_url_credentials",
            "trust_log_dir_other_readable",
            "trust_log_dir_other_writable",
            "trust_dotenv_other_readable",
            "trust_dotenv_other_writable",
            "credential_env_extra_providers",
            "approval_reason_policy",
            "policy_hooks_external_code",
        }
        healthy = all(ok for n, ok, _ in checks if n not in soft)
        payload = {
            "schema": "replayt.doctor_report.v1",
            "healthy": healthy,
            "checks": [{"name": n, "ok": o, "detail": d, "hint": hints.get(n)} for n, o, d in checks],
            "credential_env": llm_credential_env_presence(),
            "ci_artifacts": ci_artifacts_payload(ci_artifacts),
            "resolved_paths": {
                "log_dir": str(resolved_log_dir),
                "sqlite": str(resolved_sqlite) if resolved_sqlite is not None else None,
            },
        }
        if target_payload is not None:
            payload["target"] = target_payload
        typer.echo(json.dumps(payload, indent=2))
        raise typer.Exit(code=0 if healthy else 1)
    for name, ok, detail in checks:
        icon = "OK" if ok else "WARN"
        typer.echo(f"[{icon}] {name}: {detail}")
        if not ok and name in hints:
            typer.echo(f"       -> {hints[name]}")
    typer.echo(
        "Tip: `replayt try --list` shows packaged tutorial workflows you can run without a local file "
        "(offline unless --live). "
        "For YAML targets, install the extra: pip install 'replayt[yaml]'."
    )


def register(app: typer.Typer) -> None:
    app.command("doctor")(cmd_doctor)
