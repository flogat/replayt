from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from replayt.cli.main import REPLAY_HTML_CSS, _replay_html, app


def test_cli_graph_smoke() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["graph", "replayt_examples.issue_triage:wf"])
    assert r.exit_code == 0
    assert "flowchart TD" in r.stdout


def test_cli_run_inspect_and_replay(tmp_path: Path) -> None:
    runner = CliRunner()

    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.issue_triage:wf",
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
    gi = tmp_path / ".gitignore"
    assert gi.is_file()
    assert ".replayt/" in gi.read_text(encoding="utf-8")
    r2 = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r2.exit_code == 1
    r3 = runner.invoke(app, ["init", "--path", str(tmp_path), "--force"])
    assert r3.exit_code == 0


def test_cli_seal_writes_manifest(tmp_path: Path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"x"}',
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    seal = runner.invoke(app, ["seal", run_id, "--log-dir", str(tmp_path)])
    assert seal.exit_code == 0
    manifest_path = tmp_path / f"{run_id}.seal.json"
    assert manifest_path.is_file()
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["schema"] == "replayt.seal.v1"
    assert data["run_id"] == run_id
    assert len(data["line_sha256"]) == data["line_count"]


def test_cli_run_dry_check() -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--dry-check",
            "--inputs-json",
            '{"customer_name":"Pat"}',
        ],
    )
    assert r.exit_code == 0
    assert "dry check passed" in r.stdout
    assert "Next: replayt run" in r.stdout


def test_cli_try_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--log-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "workflow=hello_world_tutorial@1" in r.stdout


def test_cli_ci_runs_with_stderr_banner(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "ci",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Z"}',
        ],
    )
    assert r.exit_code == 0
    assert "replayt ci:" in (r.stderr or "")


def test_cli_report_stakeholder_omits_token_table(tmp_path: Path) -> None:
    workflow_path = tmp_path / "rep_stake.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("rep_stake")
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
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    report = runner.invoke(
        app,
        ["report", run_id, "--log-dir", str(tmp_path), "--style", "stakeholder"],
    )
    assert report.exit_code == 0
    assert "Run summary" in report.stdout
    assert "Token Usage" not in report.stdout
    assert "omitted" in report.stdout.lower()


def test_cli_report_has_no_external_cdn(tmp_path: Path) -> None:
    workflow_path = tmp_path / "rep_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("rep_mini")
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
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    report = runner.invoke(app, ["report", run_id, "--log-dir", str(tmp_path)])
    assert report.exit_code == 0
    assert "cdn.tailwindcss.com" not in report.stdout
    assert "rp-body" in report.stdout


def test_cli_run_timeout_subprocess_kills_slow_step(tmp_path: Path) -> None:
    slow = tmp_path / "slow_flow.py"
    slow.write_text(
        """
import time
from replayt.workflow import Workflow

wf = Workflow("slow")
wf.set_initial("s")

@wf.step("s")
def s(ctx):
    time.sleep(60)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(app, ["run", str(slow), "--log-dir", str(tmp_path), "--timeout", "2", "--dry-run"])
    assert r.exit_code == 1
    assert "timed out" in (r.stderr or "").lower()


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
            "replayt_examples.issue_triage:wf",
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
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    cfg, cfg_path = cfg_mod.get_project_config()
    assert cfg.get("log_dir") == ".logs/runs"
    assert cfg.get("log_mode") == "full"
    assert cfg.get("timeout") == 30
    assert cfg_path is not None
    assert "pyproject.toml" in cfg_path


def test_project_config_doctor_output(tmp_path: Path, monkeypatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nlog_dir = "my_logs"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "project_config" in result.stdout
    assert "pyproject.toml" in result.stdout


def test_cli_doctor_skip_connectivity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--skip-connectivity"])
    assert result.exit_code == 0
    assert "skipped" in result.stdout.lower()


def test_cli_stats_respects_max_runs(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    for rid in ("run-a", "run-b", "run-c"):
        lines = [
            {
                "ts": "2025-06-01T12:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            },
            {
                "ts": "2025-06-01T12:01:00+00:00",
                "run_id": rid,
                "seq": 2,
                "type": "run_completed",
                "payload": {"status": "completed"},
            },
        ]
        (log_dir / f"{rid}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n",
            encoding="utf-8",
        )
    runner = CliRunner()
    out = runner.invoke(app, ["stats", "--log-dir", str(log_dir), "--max-runs", "2", "--output", "json"])
    assert out.exit_code == 0
    data = json.loads(out.stdout)
    assert data["runs_total_on_disk"] == 3
    assert data["runs_scanned"] == 2
    assert data["max_runs"] == 2


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


def test_init_template_yaml_runs_all_states(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    runner = CliRunner()
    runner.invoke(app, ["init", "--path", str(tmp_path), "--template", "yaml"])
    wf_file = tmp_path / "workflow.yaml"
    result = runner.invoke(app, ["run", str(wf_file), "--log-dir", str(tmp_path / "logs")])
    assert result.exit_code == 0
    assert "status=completed" in result.stdout
    run_id = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("run_id="))
    inspect_result = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path / "logs"), "--output", "json"])
    assert inspect_result.exit_code == 0
    import json as _json

    data = _json.loads(inspect_result.stdout)
    visited = [e["payload"]["state"] for e in data["events"] if e["type"] == "state_entered"]
    assert visited == ["greet", "process", "done"]


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
    assert "cdn.tailwindcss.com" not in result.stdout
    assert "rp-body" in result.stdout
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
    assert "cdn.tailwindcss.com" not in content
    assert "rp-body" in content
    assert run_id in content


def test_diff_command_text_and_json(tmp_path: Path) -> None:
    workflow_path = tmp_path / "diff_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("diff_test")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("x", ctx.get("x", 0))
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    run_a = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run_a.exit_code == 0
    id_a = next(line.split("=", 1)[1] for line in run_a.stdout.splitlines() if line.startswith("run_id="))

    run_b = runner.invoke(
        app, ["run", str(workflow_path), "--log-dir", str(tmp_path), "--inputs-json", '{"x": 99}']
    )
    assert run_b.exit_code == 0
    id_b = next(line.split("=", 1)[1] for line in run_b.stdout.splitlines() if line.startswith("run_id="))

    text_result = runner.invoke(app, ["diff", id_a, id_b, "--log-dir", str(tmp_path)])
    assert text_result.exit_code == 0
    assert "Comparing" in text_result.stdout
    assert "(same)" in text_result.stdout

    json_result = runner.invoke(app, ["diff", id_a, id_b, "--log-dir", str(tmp_path), "--output", "json"])
    assert json_result.exit_code == 0
    import json as _json

    payload = _json.loads(json_result.stdout)
    assert payload["run_a"] == id_a
    assert payload["run_b"] == id_b
    assert "status" in payload


def test_diff_command_with_sqlite(tmp_path: Path) -> None:
    workflow_path = tmp_path / "diff_sqlite_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("diff_sqlite")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    db_path = tmp_path / "events.sqlite3"
    runner = CliRunner()
    run_a = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path / "jsonl"), "--sqlite", str(db_path)],
    )
    assert run_a.exit_code == 0
    id_a = next(line.split("=", 1)[1] for line in run_a.stdout.splitlines() if line.startswith("run_id="))

    run_b = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path / "jsonl"), "--sqlite", str(db_path)],
    )
    assert run_b.exit_code == 0
    id_b = next(line.split("=", 1)[1] for line in run_b.stdout.splitlines() if line.startswith("run_id="))

    result = runner.invoke(app, ["diff", id_a, id_b, "--sqlite", str(db_path)])
    assert result.exit_code == 0
    assert "Comparing" in result.stdout


def test_report_includes_tool_call_names(tmp_path: Path) -> None:
    workflow_path = tmp_path / "tool_report_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("tool_report")
wf.set_initial("use_tool")

def add(a: int, b: int) -> int:
    return a + b

@wf.step("use_tool")
def use_tool(ctx):
    ctx.tools.register(add)
    ctx.tools.call("add", {"a": 1, "b": 2})
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
    assert "add" in result.stdout


def test_cli_validate_rejects_invalid_initial_state(tmp_path: Path) -> None:
    wf_path = tmp_path / "bad_init.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("bad_init")
wf.set_initial("does_not_exist")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(app, ["validate", str(wf_path)])
    assert r.exit_code == 1
    assert "initial state" in (r.stdout + r.stderr)


def test_cli_run_preflight_invalid_initial(tmp_path: Path) -> None:
    wf_path = tmp_path / "bad_init2.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("bad_init2")
wf.set_initial("nope")

@wf.step("other")
def other(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(app, ["run", str(wf_path), "--log-dir", str(tmp_path)])
    assert r.exit_code == 1
    assert "INVALID" in (r.stdout + r.stderr)


def test_cli_export_run_tarball(tmp_path: Path) -> None:
    import tarfile

    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--metadata-json",
            '{"experiment":"a"}',
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    tar_path = tmp_path / "bundle.tar.gz"
    ex = runner.invoke(
        app,
        ["export-run", rid, "--log-dir", str(tmp_path), "--out", str(tar_path), "--export-mode", "redacted"],
    )
    assert ex.exit_code == 0
    with tarfile.open(tar_path, "r:gz") as tf:
        names = tf.getnames()
        assert any(n.endswith("events.jsonl") for n in names)
        member = [n for n in names if n.endswith("events.jsonl")][0]
        data = tf.extractfile(member).read().decode()
    first = json.loads(data.splitlines()[0])
    assert first["type"] == "run_started"
    assert first["payload"].get("inputs") == {}
    assert first["payload"].get("run_metadata") == {"experiment": "a"}


def test_cli_runs_filter_run_meta(tmp_path: Path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--metadata-json",
            '{"branch":"main"}',
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    r2 = runner.invoke(
        app, ["runs", "--log-dir", str(tmp_path), "--run-meta", "branch=main", "--limit", "5"]
    )
    assert r2.exit_code == 0
    assert rid in r2.stdout


def test_cli_log_schema_stdout() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["log-schema"])
    assert r.exit_code == 0
    assert "replayt JSONL event line" in r.stdout
    assert "$schema" in r.stdout


def test_cli_report_diff_html(tmp_path: Path) -> None:
    wf = tmp_path / "rd.py"
    wf.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("rd")
wf.set_initial("s")

@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    ra = runner.invoke(app, ["run", str(wf), "--log-dir", str(tmp_path)])
    rb = runner.invoke(app, ["run", str(wf), "--log-dir", str(tmp_path)])
    assert ra.exit_code == 0 and rb.exit_code == 0
    id_a = next(line.split("=", 1)[1] for line in ra.stdout.splitlines() if line.startswith("run_id="))
    id_b = next(line.split("=", 1)[1] for line in rb.stdout.splitlines() if line.startswith("run_id="))
    out = tmp_path / "diff.html"
    r = runner.invoke(app, ["report-diff", id_a, id_b, "--log-dir", str(tmp_path), "--out", str(out)])
    assert r.exit_code == 0
    html = out.read_text(encoding="utf-8")
    assert "Run comparison" in html
    assert id_a in html and id_b in html


def test_replayt_log_dir_env_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_root = tmp_path / "fromenv"
    log_root.mkdir()
    monkeypatch.setenv("REPLAYT_LOG_DIR", str(log_root))
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--inputs-json",
            '{"customer_name":"Sam"}',
        ],
    )
    assert r.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in r.stdout.splitlines() if line.startswith("run_id="))
    assert (log_root / f"{rid}.jsonl").is_file()


def test_cli_try_runs_offline_by_default(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--log-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "Dry run:" in r.stdout


def test_cli_validate_strict_graph_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf = tmp_path / "bad.py"
    wf.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("bad")
wf.set_initial("a")

@wf.step("a")
def a(ctx):
    return "b"

@wf.step("b")
def b(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    runner = CliRunner()
    out = runner.invoke(app, ["validate", "bad:wf", "--strict-graph"])
    assert out.exit_code == 1
    combined = (out.stdout + out.stderr).lower()
    assert "strict graph" in combined


def test_cli_ci_writes_junit_xml(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "ci",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--junit-xml",
            str(junit),
        ],
    )
    assert r.exit_code == 0
    assert junit.is_file()
    text = junit.read_text(encoding="utf-8")
    assert "testsuite" in text
    assert "workflow_run" in text


def test_cli_resume_hook_failure_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    exe = json.dumps(sys.executable)
    (tmp_path / ".replaytrc.toml").write_text(
        f"resume_hook = [{exe}, \"-c\", \"import sys; sys.exit(3)\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = CliRunner()
    run = runner.invoke(app, ["run", "approval_flow:wf", "--log-dir", str(tmp_path)])
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    resume = runner.invoke(
        app,
        ["resume", "approval_flow:wf", run_id, "--approval", "ship", "--log-dir", str(tmp_path)],
    )
    assert resume.exit_code == 1
    assert "resume_hook" in (resume.stdout + resume.stderr).lower()


def test_cli_validate_format_json_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["validate", str(wf_path), "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["schema"] == "replayt.validate_report.v1"
    assert data["ok"] is True


def test_cli_run_dry_check_json_invalid_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            str(wf_path),
            "--dry-check",
            "--inputs-json",
            "[]",
            "--output",
            "json",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["ok"] is False


def test_cli_run_inputs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    ctx.set("k", ctx.get("k"))
    return None
""".strip(),
        encoding="utf-8",
    )
    inp = tmp_path / "inputs.json"
    inp.write_text('{"k": 42}', encoding="utf-8")
    logd = tmp_path / "logs"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(logd), "--inputs-file", str(inp)],
    )
    assert r.exit_code == 0


def test_cli_run_rejects_inputs_json_and_file_together(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    inp = tmp_path / "i.json"
    inp.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            str(wf_path),
            "--log-dir",
            str(tmp_path / "logs"),
            "--inputs-json",
            "{}",
            "--inputs-file",
            str(inp),
        ],
    )
    assert r.exit_code == 2
    assert "only one" in (r.stdout + r.stderr).lower()


def test_cli_run_inputs_file_whitespace_only_is_empty_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    assert ctx.get("k") is None
    return None
""".strip(),
        encoding="utf-8",
    )
    inp = tmp_path / "i.json"
    inp.write_text("  \n\t  ", encoding="utf-8")
    logd = tmp_path / "logs"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["run", str(wf_path), "--log-dir", str(logd), "--inputs-file", str(inp)])
    assert r.exit_code == 0


def test_cli_run_inputs_file_requires_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    inp = tmp_path / "bad.txt"
    inp.write_bytes(b"\xff\xfe{\x22x\x22:1}")  # not valid UTF-8
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-file", str(inp)],
    )
    assert r.exit_code == 2
    assert "utf-8" in (r.stdout + r.stderr).lower()


def test_cli_validate_inputs_file_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    inp = tmp_path / "i.json"
    inp.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["validate", str(wf_path), "--inputs-file", str(inp), "--format", "json"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["ok"] is False
    assert any("inputs" in err.lower() for err in data["errors"])


def test_cli_ci_appends_github_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "ci",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--github-summary",
        ],
    )
    assert r.exit_code == 0
    text = summary.read_text(encoding="utf-8")
    assert "## replayt ci" in text
    assert "hello_world_tutorial" in text


def test_cli_ci_junit_xml_forwards_through_timeout_subprocess(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "ci",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--junit-xml",
            str(junit),
            "--timeout",
            "120",
        ],
    )
    assert r.exit_code == 0
    assert junit.is_file()
    assert "testsuite" in junit.read_text(encoding="utf-8")


def test_cli_run_junit_xml_via_replayt_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    junit = tmp_path / "from_env.xml"
    monkeypatch.setenv("REPLAYT_JUNIT_XML", str(junit))
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
        ],
    )
    assert r.exit_code == 0
    assert junit.is_file()


def test_cli_doctor_format_json_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["doctor", "--skip-connectivity", "--format", "json"],
    )
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["schema"] == "replayt.doctor_report.v1"
    assert data["healthy"] is True


def test_cli_bundle_export_creates_tarball(tmp_path: Path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"x"}',
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    out_tar = tmp_path / "b.tar.gz"
    be = runner.invoke(
        app,
        ["bundle-export", run_id, "--out", str(out_tar), "--log-dir", str(tmp_path)],
    )
    assert be.exit_code == 0
    assert out_tar.is_file()
    with tarfile.open(out_tar, "r:gz") as tf:
        names = tf.getnames()
    assert any(n.endswith("/report.html") for n in names)
    assert any(n.endswith("/timeline.html") for n in names)
    assert any(n.endswith("/events.jsonl") for n in names)


def test_cli_resume_reason_and_actor_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    resume = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path),
            "--reason",
            "ticket-1",
            "--actor-json",
            '{"email":"a@example.com"}',
            "--resolver",
            "bridge",
        ],
    )
    assert resume.exit_code == 0
    raw = (tmp_path / f"{run_id}.jsonl").read_text(encoding="utf-8")
    resolved = [json.loads(line) for line in raw.splitlines() if '"approval_resolved"' in line]
    assert resolved
    p = resolved[-1]["payload"]
    assert p["reason"] == "ticket-1"
    assert p["resolver"] == "bridge"
    assert p["actor"] == {"email": "a@example.com"}


def test_cli_init_ci_github_writes_workflow(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--path", str(tmp_path), "--ci", "github"])
    assert r.exit_code == 0
    wf_yml = tmp_path / ".github" / "workflows" / "replayt.yml"
    assert wf_yml.is_file()
    text = wf_yml.read_text(encoding="utf-8")
    assert "replayt validate" in text
    assert "CHANGE_ME_MODULE:wf" in text


def test_cli_stats_includes_run_when_summary_last_ts_unparseable(tmp_path: Path) -> None:
    """Unparseable last_ts skips day cutoff exclusion (parse_iso_ts returns None)."""

    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    rid = "run-bad-last-ts"
    lines = [
        {
            "ts": "2025-06-01T12:00:00+00:00",
            "run_id": rid,
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "not-an-iso-timestamp",
            "run_id": rid,
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / f"{rid}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    out = runner.invoke(app, ["stats", "--log-dir", str(log_dir), "--days", "1", "--output", "json"])
    assert out.exit_code == 0
    data = json.loads(out.stdout)
    assert data["runs_included"] == 1


def test_cli_gc_skips_delete_when_last_event_ts_unparseable(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    rid = "old-bad-ts"
    lines = [
        {
            "ts": "1999-01-01T00:00:00+00:00",
            "run_id": rid,
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "bogus",
            "run_id": rid,
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / f"{rid}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    out = runner.invoke(app, ["gc", "--log-dir", str(log_dir), "--older-than", "1d"])
    assert out.exit_code == 0
    assert (log_dir / f"{rid}.jsonl").is_file()
    assert "deleted 0 run(s)" in out.stdout

