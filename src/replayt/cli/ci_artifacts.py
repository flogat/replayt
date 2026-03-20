"""Optional CI outputs (JUnit XML, GitHub Actions step summary)."""

from __future__ import annotations

import os
from pathlib import Path

from replayt.runner import RunResult
from replayt.workflow import Workflow


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


def append_github_step_summary(wf: Workflow, result: RunResult) -> None:
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
    if result.error:
        lines.append(f"- **error:** `{result.error}`")
    lines.append("")
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def resolve_ci_junit_path(explicit: Path | None) -> Path | None:
    """Explicit ``replayt ci --junit-xml`` wins; else ``REPLAYT_JUNIT_XML`` for ad-hoc scripts."""

    if explicit is not None:
        return explicit
    env_j = os.environ.get("REPLAYT_JUNIT_XML", "").strip()
    return Path(env_j) if env_j else None


def should_write_github_step_summary(explicit: bool) -> bool:
    return explicit or os.environ.get("REPLAYT_GITHUB_SUMMARY") == "1"


def write_ci_artifacts(
    wf: Workflow,
    result: RunResult,
    *,
    junit_path: Path | None,
    github_summary: bool,
) -> None:
    if junit_path is not None:
        write_junit_xml(junit_path, wf=wf, result=result)
    if github_summary:
        append_github_step_summary(wf, result)
