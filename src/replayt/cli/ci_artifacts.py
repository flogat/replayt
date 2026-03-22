"""Optional CI outputs (JUnit XML, GitHub Actions step summary, machine-readable summary)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from replayt.cli.run_support import exit_code_for_run_result
from replayt.runner import RunResult
from replayt.workflow import Workflow


@dataclass(frozen=True)
class ResolvedCIArtifacts:
    junit_xml: Path | None
    junit_xml_source: str
    summary_json: Path | None
    summary_json_source: str
    github_summary_requested: bool
    github_summary_requested_source: str
    github_step_summary: Path | None
    github_step_summary_source: str


def parse_ci_metadata_from_env() -> dict[str, Any] | None:
    """Parse ``REPLAYT_CI_METADATA_JSON`` when set; must be a JSON object.

    Used to enrich ``replayt.ci_run_summary.v1`` with pipeline correlation fields
    (build id, commit, job URL) supplied by the caller's CI shell.
    """

    raw = os.environ.get("REPLAYT_CI_METADATA_JSON", "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"REPLAYT_CI_METADATA_JSON is not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(val, dict):
        raise ValueError(
            "REPLAYT_CI_METADATA_JSON must be a JSON object (mapping), not an array or scalar."
        )
    return val


def _xml_escape_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_escape_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def write_junit_xml(path: Path, *, wf: Workflow, result: RunResult) -> None:
    """Write a minimal JUnit file for CI systems (one testcase per invocation)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    cls_name = _xml_escape_attr(f"{wf.name}@{wf.version}")
    msg = f"status={result.status} run_id={result.run_id}"
    if result.error:
        msg += f" error={result.error}"
    msg_esc = _xml_escape_text(msg)
    msg_attr = _xml_escape_attr(msg)
    if result.status == "completed":
        failures = errors = skipped = 0
        case_inner = ""
    elif result.status == "paused":
        failures = errors = 0
        skipped = 1
        case_inner = f'<skipped message="{msg_attr}"/>'
    else:
        failures = 1
        errors = skipped = 0
        case_inner = f'<failure message="run failed">{msg_esc}</failure>'
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<testsuites>\n"
        f'  <testsuite name="replayt" tests="1" failures="{failures}" errors="{errors}" skipped="{skipped}">\n'
        f'    <testcase name="workflow_run" classname="{cls_name}">{case_inner}</testcase>\n'
        "  </testsuite>\n"
        "</testsuites>\n"
    )
    path.write_text(doc, encoding="utf-8")


def append_github_step_summary(
    wf: Workflow,
    result: RunResult,
    *,
    duration_ms: int | None = None,
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## replayt ci",
        "",
        f"- **Workflow:** `{wf.name}@{wf.version}`",
        f"- **run_id:** `{result.run_id}`",
        f"- **status:** `{result.status}`",
    ]
    if duration_ms is not None:
        lines.append(f"- **duration_ms:** `{duration_ms}`")
    if result.error:
        lines.append(f"- **error:** `{result.error}`")
    lines.append("")
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_summary_json(
    path: Path,
    *,
    wf: Workflow,
    result: RunResult,
    target: str,
    log_dir: Path,
    sqlite: Path | None = None,
    dry_run: bool = False,
    duration_ms: int | None = None,
    ci_metadata: dict[str, Any] | None = None,
) -> None:
    """Write one machine-readable run summary artifact for CI wrappers."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": "replayt.ci_run_summary.v1",
        "workflow": f"{wf.name}@{wf.version}",
        "workflow_name": wf.name,
        "workflow_version": wf.version,
        "run_id": result.run_id,
        "status": result.status,
        "final_state": result.final_state,
        "error": result.error,
        "exit_code": exit_code_for_run_result(result),
        "target": target,
        "log_dir": str(log_dir.resolve()),
        "dry_run": dry_run,
    }
    if sqlite is not None:
        payload["sqlite"] = str(sqlite.resolve())
    else:
        payload["sqlite"] = None
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if ci_metadata is not None:
        payload["ci_metadata"] = ci_metadata
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def resolve_ci_junit_path(explicit: Path | None) -> Path | None:
    """Explicit ``replayt ci --junit-xml`` wins; else ``REPLAYT_JUNIT_XML`` for ad-hoc scripts."""

    if explicit is not None:
        return explicit
    env_j = os.environ.get("REPLAYT_JUNIT_XML", "").strip()
    return Path(env_j) if env_j else None


def resolve_ci_summary_json_path(explicit: Path | None) -> Path | None:
    """Explicit ``replayt ci --summary-json`` wins; else ``REPLAYT_SUMMARY_JSON`` for scripts."""

    if explicit is not None:
        return explicit
    env_summary = os.environ.get("REPLAYT_SUMMARY_JSON", "").strip()
    return Path(env_summary) if env_summary else None


def should_write_github_step_summary(explicit: bool) -> bool:
    return explicit or os.environ.get("REPLAYT_GITHUB_SUMMARY") == "1"


def resolve_ci_artifacts(
    *,
    explicit_junit_xml: Path | None,
    explicit_summary_json: Path | None,
    explicit_github_summary: bool,
) -> ResolvedCIArtifacts:
    env_junit = os.environ.get("REPLAYT_JUNIT_XML", "").strip()
    env_summary = os.environ.get("REPLAYT_SUMMARY_JSON", "").strip()
    env_github_toggle = os.environ.get("REPLAYT_GITHUB_SUMMARY", "").strip()
    env_github_step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()

    return ResolvedCIArtifacts(
        junit_xml=resolve_ci_junit_path(explicit_junit_xml),
        junit_xml_source=(
            "cli:--junit-xml" if explicit_junit_xml is not None else "env:REPLAYT_JUNIT_XML" if env_junit else "unset"
        ),
        summary_json=resolve_ci_summary_json_path(explicit_summary_json),
        summary_json_source=(
            "cli:--summary-json"
            if explicit_summary_json is not None
            else "env:REPLAYT_SUMMARY_JSON"
            if env_summary
            else "unset"
        ),
        github_summary_requested=should_write_github_step_summary(explicit_github_summary),
        github_summary_requested_source=(
            "cli:--github-summary"
            if explicit_github_summary
            else "env:REPLAYT_GITHUB_SUMMARY"
            if env_github_toggle == "1"
            else "unset"
        ),
        github_step_summary=Path(env_github_step_summary) if env_github_step_summary else None,
        github_step_summary_source="env:GITHUB_STEP_SUMMARY" if env_github_step_summary else "unset",
    )


def ci_artifacts_payload(artifacts: ResolvedCIArtifacts) -> dict[str, Any]:
    def _path_value(path: Path | None) -> str | None:
        return str(path.resolve()) if path is not None else None

    return {
        "junit_xml": {
            "path": _path_value(artifacts.junit_xml),
            "source": artifacts.junit_xml_source,
        },
        "summary_json": {
            "path": _path_value(artifacts.summary_json),
            "source": artifacts.summary_json_source,
        },
        "github_summary": {
            "requested": artifacts.github_summary_requested,
            "requested_source": artifacts.github_summary_requested_source,
            "path": _path_value(artifacts.github_step_summary),
            "path_source": artifacts.github_step_summary_source,
        },
    }


def write_ci_artifacts(
    wf: Workflow,
    result: RunResult,
    *,
    junit_path: Path | None,
    summary_json_path: Path | None,
    github_summary: bool,
    target: str,
    log_dir: Path,
    sqlite: Path | None = None,
    dry_run: bool = False,
    duration_ms: int | None = None,
    ci_metadata: dict[str, Any] | None = None,
) -> None:
    if junit_path is not None:
        write_junit_xml(junit_path, wf=wf, result=result)
    if summary_json_path is not None:
        write_summary_json(
            summary_json_path,
            wf=wf,
            result=result,
            target=target,
            log_dir=log_dir,
            sqlite=sqlite,
            dry_run=dry_run,
            duration_ms=duration_ms,
            ci_metadata=ci_metadata,
        )
    if github_summary:
        append_github_step_summary(wf, result, duration_ms=duration_ms)
