"""Command: version."""

from __future__ import annotations

import json
import sys
from typing import Literal

import typer

import replayt

VERSION_REPORT_SCHEMA = "replayt.version_report.v1"


def build_version_report() -> dict[str, object]:
    vi = sys.version_info
    return {
        "schema": VERSION_REPORT_SCHEMA,
        "replayt_version": replayt.__version__,
        "python": {
            "version": f"{vi.major}.{vi.minor}.{vi.micro}",
            "major": vi.major,
            "minor": vi.minor,
            "micro": vi.micro,
            "releaselevel": vi.releaselevel,
            "serial": vi.serial,
        },
        "platform": sys.platform,
        "cli_machine_readable_schemas": {
            "version_report": VERSION_REPORT_SCHEMA,
            "workflow_contract": "replayt.workflow_contract.v1",
            "validate_report": "replayt.validate_report.v1",
            "doctor_report": "replayt.doctor_report.v1",
            "config_report": "replayt.config_report.v1",
            "ci_run_summary": "replayt.ci_run_summary.v1",
        },
    }


def cmd_version(
    output: Literal["text", "json"] = typer.Option(
        "text",
        "--format",
        "-f",
        help="text (default) or json (stable schema for CI / compatibility probes).",
    ),
) -> None:
    """Print replayt and Python runtime versions (machine-readable JSON optional)."""

    payload = build_version_report()
    if output == "json":
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"replayt {payload['replayt_version']}")
    py = payload["python"]
    if isinstance(py, dict):
        typer.echo(f"python {py['version']}")
    typer.echo(f"platform {payload['platform']}")


def register(app: typer.Typer) -> None:
    app.command("version")(cmd_version)
