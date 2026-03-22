"""Command: version."""

from __future__ import annotations

import json
import sys
from typing import Literal

import typer

import replayt
from replayt.cli.config import SUPPORTED_CONFIG_KEYS
from replayt.cli.run_support import RUN_RESULT_SCHEMA, build_policy_hook_env_catalog

VERSION_REPORT_SCHEMA = "replayt.version_report.v1"

# Stable schema ids emitted by repo-local scripts under scripts/ (maintainer_checks loads these).
MAINTAINER_SCRIPT_SCHEMAS: dict[str, str] = {
    "unreleased_changelog": "replayt.unreleased_changelog.v1",
    "docs_index_report": "replayt.docs_index_report.v1",
    "version_consistency": "replayt.version_consistency.v1",
    "example_catalog_contract": "replayt.example_catalog_contract.v1",
    "public_api_report": "replayt.public_api_report.v1",
    "maintainer_checks": "replayt.maintainer_checks.v1",
    "skill_invocation": "replayt.skill_invocation.v1",
}


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
        "supported_project_config_keys": sorted(SUPPORTED_CONFIG_KEYS),
        "maintainer_script_schemas": dict(sorted(MAINTAINER_SCRIPT_SCHEMAS.items())),
        "policy_hook_env_catalog": build_policy_hook_env_catalog(),
        "cli_machine_readable_schemas": {
            "version_report": VERSION_REPORT_SCHEMA,
            "workflow_contract": "replayt.workflow_contract.v1",
            "workflow_contract_check": "replayt.workflow_contract_check.v1",
            "validate_report": "replayt.validate_report.v1",
            "doctor_report": "replayt.doctor_report.v1",
            "config_report": "replayt.config_report.v1",
            "ci_run_summary": "replayt.ci_run_summary.v1",
            "run_result": RUN_RESULT_SCHEMA,
            "inspect_report": "replayt.inspect_report.v1",
            "runs_report": "replayt.runs_report.v1",
            "stats_report": "replayt.stats_report.v1",
            "diff_report": "replayt.diff_report.v1",
            "bundle_export": "replayt.bundle_export.v1",
            "export_bundle": "replayt.export_bundle.v1",
            "export_seal": "replayt.export_seal.v1",
            "seal": "replayt.seal.v1",
            "verify_seal_report": "replayt.verify_seal_report.v1",
            "try_examples": "replayt.try_examples.v1",
            "try_copy": "replayt.try_copy.v1",
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
