from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from replayt.cli.main import app


def test_cli_graph_smoke() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["graph", "examples.issue_triage:wf"])
    assert r.exit_code == 0
    assert "flowchart TD" in r.stdout


def test_cli_run_inspect_and_replay(tmp_path: Path) -> None:
    runner = CliRunner()

    run = runner.invoke(
        app,
        [
            "run",
            "examples.issue_triage:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"issue":{"title":"Bug","body":"too short"}}',
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path)])
    assert inspect.exit_code == 0
    assert "run_completed" in inspect.stdout
    assert "workflow=github_issue_triage@1" in inspect.stdout

    replay = runner.invoke(app, ["replay", run_id, "--log-dir", str(tmp_path)])
    assert replay.exit_code == 0
    assert "state_entered" in replay.stdout
    assert "transition" in replay.stdout


def test_cli_resume_approval_flow(tmp_path: Path, monkeypatch) -> None:
    module_path = tmp_path / "approval_flow.py"
    module_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("approval_flow")
wf.set_initial("gate")
wf.note_transition("gate", "done")

@wf.step("gate")
def gate(ctx):
    if ctx.is_approved("ship"):
        return "done"
    ctx.request_approval("ship", summary="Ship it?")

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = CliRunner()
    run = runner.invoke(app, ["run", "approval_flow:wf", "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    assert "status=paused" in run.stdout
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    resume = runner.invoke(
        app,
        ["resume", "approval_flow:wf", run_id, "--approval", "ship", "--log-dir", str(tmp_path)],
    )
    assert resume.exit_code == 0
    assert "status=completed" in resume.stdout


def test_cli_supports_python_file_targets(tmp_path: Path) -> None:
    workflow_path = tmp_path / "mini_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("mini")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("ok", True)
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "workflow=mini@1" in result.stdout


def test_cli_supports_yaml_file_targets(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    workflow_path = tmp_path / "mini_flow.yaml"
    workflow_path.write_text(
        """
name: yaml-mini
version: 3
initial: start
steps:
  start:
    set:
      ok: true
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "workflow=yaml-mini@3" in result.stdout


def test_cli_runs_and_doctor(tmp_path: Path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "examples.issue_triage:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"issue":{"title":"Bug report","body":"This body is definitely long enough to pass validation."}}',
        ],
    )
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    runs = runner.invoke(app, ["runs", "--log-dir", str(tmp_path)])
    assert runs.exit_code == 0
    assert run_id in runs.stdout

    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    assert "python" in doctor.stdout
