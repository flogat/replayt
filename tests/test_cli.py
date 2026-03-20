from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from replayt.cli.main import REPLAY_HTML_CSS, _replay_html, app


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
    assert run.exit_code == 2  # paused (approval pending)
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


def test_cli_run_json_output_and_pause_exit(tmp_path: Path) -> None:
    workflow_path = tmp_path / "json_out_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("json_out")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("x", 1)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            str(workflow_path),
            "--log-dir",
            str(tmp_path),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert '"status": "completed"' in result.stdout
    assert '"run_id"' in result.stdout


def test_cli_init_scaffold(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r.exit_code == 0
    assert (tmp_path / "workflow.py").is_file()
    assert (tmp_path / ".env.example").is_file()
    r2 = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r2.exit_code == 1
    r3 = runner.invoke(app, ["init", "--path", str(tmp_path), "--force"])
    assert r3.exit_code == 0


def test_cli_stats_and_replay_html(tmp_path: Path) -> None:
    workflow_path = tmp_path / "stats_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("stats_mini")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("ok", True)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    run = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    stats = runner.invoke(app, ["stats", "--log-dir", str(tmp_path), "--output", "json"])
    assert stats.exit_code == 0
    assert '"runs_included"' in stats.stdout
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    html_out = runner.invoke(
        app,
        ["replay", run_id, "--log-dir", str(tmp_path), "--format", "html"],
    )
    assert html_out.exit_code == 0
    assert "<style>" in html_out.stdout
    assert run_id in html_out.stdout


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
    assert "replayt" in doctor.stdout.lower()


def test_cli_inspect_and_replay_can_read_from_sqlite(tmp_path: Path) -> None:
    workflow_path = tmp_path / "sqlite_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("sqlite_flow")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    db_path = tmp_path / "events.sqlite3"
    runner = CliRunner()
    run = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path / "jsonl"), "--sqlite", str(db_path)],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--sqlite", str(db_path)])
    assert inspect.exit_code == 0
    replay = runner.invoke(app, ["replay", run_id, "--sqlite", str(db_path)])
    assert replay.exit_code == 0
    stats = runner.invoke(app, ["stats", "--sqlite", str(db_path), "--output", "json"])
    assert stats.exit_code == 0
    runs = runner.invoke(app, ["runs", "--sqlite", str(db_path)])
    assert runs.exit_code == 0
    assert run_id in runs.stdout


def test_replay_html_embeds_valid_css() -> None:
    html = _replay_html(
        "run-123",
        [
            {"seq": 1, "type": "run_started", "payload": {"workflow_name": "demo", "workflow_version": "1"}},
            {"seq": 2, "type": "run_completed", "payload": {"status": "completed"}},
        ],
    )

    assert "body{" in REPLAY_HTML_CSS
    assert "body{{" not in REPLAY_HTML_CSS
    assert "<style>" in html
    assert "body{" in html
    assert "body{{" not in html


def test_project_config_from_pyproject_toml(tmp_path: Path, monkeypatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.replayt]\nlog_dir = ".logs/runs"\nlog_mode = "full"\ntimeout = 30\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.main as cli_mod

    monkeypatch.setattr(cli_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cli_mod, "_PROJECT_CONFIG_PATH", None)

    cfg, cfg_path = cli_mod._get_project_config()
    assert cfg.get("log_dir") == ".logs/runs"
    assert cfg.get("log_mode") == "full"
    assert cfg.get("timeout") == 30
    assert cfg_path is not None
    assert "pyproject.toml" in cfg_path


def test_project_config_doctor_output(tmp_path: Path, monkeypatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nlog_dir = "my_logs"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.main as cli_mod

    monkeypatch.setattr(cli_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cli_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "project_config" in result.stdout
    assert "pyproject.toml" in result.stdout


def test_init_template_approval(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--template", "approval"])
    assert result.exit_code == 0
    wf_file = tmp_path / "workflow.py"
    assert wf_file.is_file()
    content = wf_file.read_text(encoding="utf-8")
    assert "approval_workflow" in content
    assert "request_approval" in content
    assert "template=approval" in result.stdout


def test_init_template_yaml(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--template", "yaml"])
    assert result.exit_code == 0
    wf_file = tmp_path / "workflow.yaml"
    assert wf_file.is_file()
    content = wf_file.read_text(encoding="utf-8")
    assert "yaml_workflow" in content
    assert "template=yaml" in result.stdout


def test_init_template_tool_using(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--template", "tool-using"])
    assert result.exit_code == 0
    wf_file = tmp_path / "workflow.py"
    assert wf_file.is_file()
    content = wf_file.read_text(encoding="utf-8")
    assert "tool_workflow" in content


def test_dry_run_completes_without_api_key(tmp_path: Path) -> None:
    workflow_path = tmp_path / "dry_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("dry_test")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("x", 1)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.stdout
    assert "status=completed" in result.stdout


def test_dry_run_with_llm_call(tmp_path: Path) -> None:
    workflow_path = tmp_path / "dry_llm_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("dry_llm")
wf.set_initial("ask")

@wf.step("ask")
def ask(ctx):
    text = ctx.llm.complete_text(messages=[{"role": "user", "content": "hello"}])
    ctx.set("response", text)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.stdout
    assert "status=completed" in result.stdout


def test_report_generates_html(tmp_path: Path) -> None:
    workflow_path = tmp_path / "report_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("report_test")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("done", True)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    run = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    result = runner.invoke(app, ["report", run_id, "--log-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "tailwindcss" in result.stdout
    assert "Run Report" in result.stdout
    assert run_id in result.stdout
    assert "report_test" in result.stdout


def test_report_writes_to_file(tmp_path: Path) -> None:
    workflow_path = tmp_path / "report_file_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("report_file")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    run = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    out_file = tmp_path / "report.html"
    result = runner.invoke(app, ["report", run_id, "--log-dir", str(tmp_path), "--out", str(out_file)])
    assert result.exit_code == 0
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "tailwindcss" in content
    assert run_id in content

