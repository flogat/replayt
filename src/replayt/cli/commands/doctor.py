"""Command: doctor."""

from __future__ import annotations

import json
import os
import sys
from typing import Literal

import typer

from replayt.cli.config import get_project_config
from replayt.llm import LLMSettings


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
        help="text (default) or json (machine-readable; exit 1 unless healthy — see docs/CLI.md).",
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

    cfg, cfg_path = get_project_config()
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
    checks.append(("replayt_provider", True, prov or "(unset, OpenRouter preset)"))
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
    if output == "json":
        soft = {"openai_api_key", "project_config"}
        healthy = all(ok for n, ok, _ in checks if n not in soft)
        payload = {
            "schema": "replayt.doctor_report.v1",
            "healthy": healthy,
            "checks": [{"name": n, "ok": o, "detail": d, "hint": hints.get(n)} for n, o, d in checks],
        }
        typer.echo(json.dumps(payload, indent=2))
        raise typer.Exit(code=0 if healthy else 1)
    for name, ok, detail in checks:
        icon = "OK" if ok else "WARN"
        typer.echo(f"[{icon}] {name}: {detail}")
        if not ok and name in hints:
            typer.echo(f"       → {hints[name]}")
    typer.echo(
        "Tip: `replayt try` runs the PyPI tutorial workflow without a local file (offline unless --live). "
        "For YAML targets, install the extra: pip install 'replayt[yaml]'."
    )


def register(app: typer.Typer) -> None:
    app.command("doctor")(cmd_doctor)
