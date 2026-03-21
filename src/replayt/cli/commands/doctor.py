"""Command: doctor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import typer

from replayt.cli.config import (
    DEFAULT_LOG_DIR,
    get_project_config,
    resolve_llm_settings,
    resolve_log_dir,
    resolve_log_mode_setting,
    resolve_sqlite_path,
)
from replayt.cli.path_readiness import readiness_checks
from replayt.cli.targets import load_target
from replayt.cli.validation import (
    inputs_json_from_options,
    validate_workflow_graph,
    validation_report,
)
from replayt.security import log_directory_permission_trust_checks, trust_boundary_checks


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

    cfg, cfg_path = get_project_config()
    settings, llm_report = resolve_llm_settings(cfg)
    settings_error = llm_report.get("error")
    resolved_log_mode, _log_mode_source = resolve_log_mode_setting("redacted", cfg)
    resolved_log_dir = resolve_log_dir(DEFAULT_LOG_DIR)
    resolved_sqlite, _sqlite_source = resolve_sqlite_path(None, cfg, config_path=cfg_path)

    checks: list[tuple[str, bool, str]] = []
    checks.append(("replayt", True, pkg_ver))
    if cfg_path:
        checks.append(("project_config", True, cfg_path))
    else:
        checks.append(("project_config", False, "No project config found"))
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
    if settings_error is None and settings is not None:
        checks.append(("openai_base_url", True, f"{settings.base_url} ({llm_report['base_url_source']})"))
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
        try:
            import httpx

            assert settings is not None
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

    for check in trust_boundary_checks(base_url=llm_report.get("base_url"), log_mode=resolved_log_mode):
        checks.append((check.name, check.ok, check.detail))
    for check in log_directory_permission_trust_checks(resolved_log_dir):
        checks.append((check.name, check.ok, check.detail))
    for check in readiness_checks(log_dir=resolved_log_dir, sqlite=resolved_sqlite):
        checks.append((check.name, check.ok, check.detail))

    target_payload: dict[str, object] | None = None
    if target is not None:
        try:
            inputs_resolved = inputs_json_from_options(inputs_json, inputs_file)
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
        "provider_config": "set OPENAI_BASE_URL to an OpenAI-compatible gateway or use a supported preset",
        "provider_connectivity": "try replayt doctor --skip-connectivity; check OPENAI_BASE_URL",
        "trust_log_mode": "Prefer redacted or structured_only for logs that may contain sensitive text.",
        "trust_base_url_transport": "Use HTTPS for remote providers; keep plain HTTP for localhost-only gateways.",
        "trust_base_url_credentials": "Move secrets out of OPENAI_BASE_URL and into headers or env vars.",
        "trust_log_dir_other_readable": (
            "Tighten log_dir permissions so other OS accounts cannot read JSONL audit files."
        ),
        "trust_log_dir_other_writable": (
            "Tighten log_dir permissions so other OS accounts cannot append or replace run logs."
        ),
        "log_dir_ready": "Fix the resolved log_dir path or its parent-directory permissions before running replayt.",
        "sqlite_ready": "Fix the resolved sqlite path or its parent-directory permissions before enabling the mirror.",
        "target_validation": (
            "Use replayt validate TARGET or replayt doctor --target TARGET --strict-graph "
            "to inspect the preflight errors."
        ),
    }
    if output == "json":
        soft = {
            "openai_api_key",
            "project_config",
            "yaml_extra",
            "trust_log_mode",
            "trust_base_url_transport",
            "trust_base_url_credentials",
            "trust_log_dir_other_readable",
            "trust_log_dir_other_writable",
        }
        healthy = all(ok for n, ok, _ in checks if n not in soft)
        payload = {
            "schema": "replayt.doctor_report.v1",
            "healthy": healthy,
            "checks": [{"name": n, "ok": o, "detail": d, "hint": hints.get(n)} for n, o, d in checks],
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
