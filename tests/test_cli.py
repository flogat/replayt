from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import replayt
from replayt.cli.main import REPLAY_HTML_CSS, _replay_html, app
from replayt.cli.targets import load_target

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _reset_project_config_cache() -> None:
    import replayt.cli.config as cfg_mod

    cfg_mod._PROJECT_CONFIG = None
    cfg_mod._PROJECT_CONFIG_PATH = None
    cfg_mod._PROJECT_CONFIG_UNKNOWN_KEYS = None
    cfg_mod._PROJECT_CONFIG_SHADOWED_SOURCES = None
    cfg_mod._PROJECT_CONFIG_CWD = None


def test_cli_graph_smoke() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["graph", "replayt_examples.issue_triage:wf"])
    assert r.exit_code == 0
    assert "flowchart TD" in r.stdout


def test_cli_contract_json_reports_snapshot(tmp_path: Path) -> None:
    workflow_path = tmp_path / "contract_flow.py"
    workflow_path.write_text(
        """
from replayt.types import RetryPolicy
from replayt.workflow import Workflow

wf = Workflow("contract_flow", version="3")
wf.set_initial("start")
wf.note_transition("start", "done")

@wf.step("start", retries=RetryPolicy(max_attempts=4, backoff_seconds=2.0), expects={"ticket_id": str})
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["contract", str(workflow_path), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema"] == "replayt.workflow_contract.v1"
    assert isinstance(data["contract_sha256"], str)
    assert len(data["contract_sha256"]) == 64
    assert data["workflow"]["name"] == "contract_flow"
    start_step = next(step for step in data["steps"] if step["name"] == "start")
    assert start_step["retry_policy"] == {"max_attempts": 4, "backoff_seconds": 2.0}
    assert start_step["expects"] == [{"key": "ticket_id", "type": "str"}]
    assert start_step["outgoing_transitions"] == ["done"]


def test_cli_contract_snapshot_out_writes_json(tmp_path: Path) -> None:
    workflow_path = tmp_path / "contract_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("contract_flow", version="3")
wf.set_initial("start")
wf.note_transition("start", "done")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    snapshot_path = tmp_path / "contracts" / "workflow.contract.json"

    runner = CliRunner()
    result = runner.invoke(app, ["contract", str(workflow_path), "--snapshot-out", str(snapshot_path)])

    assert result.exit_code == 0
    assert snapshot_path.is_file()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "replayt.workflow_contract.v1"
    assert isinstance(payload["contract_sha256"], str)
    assert payload["workflow"]["name"] == "contract_flow"
    assert f"wrote {snapshot_path}" in result.stdout


def test_cli_contract_check_matches_snapshot(tmp_path: Path) -> None:
    workflow_path = tmp_path / "contract_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("contract_flow", version="3")
wf.set_initial("start")
wf.note_transition("start", "done")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    snapshot_path = tmp_path / "workflow.contract.json"
    runner = CliRunner()
    write = runner.invoke(app, ["contract", str(workflow_path), "--snapshot-out", str(snapshot_path)])
    assert write.exit_code == 0

    check = runner.invoke(app, ["contract", str(workflow_path), "--check", str(snapshot_path)])

    assert check.exit_code == 0
    assert f"contract matches {snapshot_path}" in check.stdout


def test_cli_contract_check_json_reports_drift(tmp_path: Path) -> None:
    workflow_path = tmp_path / "contract_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("contract_flow", version="3")
wf.set_initial("start")
wf.note_transition("start", "done")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    snapshot_path = tmp_path / "workflow.contract.json"
    runner = CliRunner()
    write = runner.invoke(app, ["contract", str(workflow_path), "--snapshot-out", str(snapshot_path)])
    assert write.exit_code == 0

    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("contract_flow", version="4")
wf.set_initial("start")
wf.note_transition("start", "done")
wf.note_transition("done", "archive")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return "archive"

@wf.step("archive")
def archive(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    check = runner.invoke(app, ["contract", str(workflow_path), "--check", str(snapshot_path), "--format", "json"])

    assert check.exit_code == 1
    payload = json.loads(check.stdout)
    assert payload["schema"] == "replayt.workflow_contract_check.v1"
    assert payload["ok"] is False
    assert payload["snapshot_path"] == str(snapshot_path)
    assert payload["workflow"]["version"] == "4"
    assert any(line.startswith("@@") for line in payload["diff"])


def test_cli_inspect_surfaces_workflow_contract_digest(tmp_path: Path) -> None:
    workflow_path = tmp_path / "digest_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("digest_flow", version="2")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    ctx.set("ok", True)
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    contract = runner.invoke(app, ["contract", str(workflow_path), "--format", "json"])
    assert contract.exit_code == 0
    contract_payload = json.loads(contract.stdout)
    contract_sha256 = contract_payload["contract_sha256"]

    run = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect_text = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path)])
    assert inspect_text.exit_code == 0
    assert f"workflow_contract_sha256={contract_sha256}" in inspect_text.stdout

    inspect_json = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "json"])
    assert inspect_json.exit_code == 0
    inspect_payload = json.loads(inspect_json.stdout)
    assert inspect_payload["summary"]["workflow_contract_sha256"] == contract_sha256

    inspect_md = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "markdown"])
    assert inspect_md.exit_code == 0
    md_out = inspect_md.stdout
    assert f"## replayt run `{run_id}`" in md_out
    assert "digest_flow@2" in md_out
    assert contract_sha256 in md_out
    assert "Stakeholder-facing report:" in md_out
    assert f"replayt report {run_id} --format markdown --style stakeholder" in md_out


def test_cli_inspect_output_markdown_rejects_event_filters(tmp_path: Path) -> None:
    workflow_path = tmp_path / "filter_md_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("filter_md_flow", version="1")
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

    r = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--output",
            "markdown",
            "--event-type",
            "run_started",
        ],
    )
    assert r.exit_code != 0
    out = (r.stdout or "") + (r.stderr or "")
    assert "markdown summarizes the full run" in out


def test_cli_inspect_output_markdown_includes_resume_hint_when_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "approval_flow_md.py"
    module_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("approval_flow_md")
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
    run = runner.invoke(app, ["run", "approval_flow_md:wf", "--log-dir", str(tmp_path)])
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect_md = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "markdown"])
    assert inspect_md.exit_code == 0
    out = inspect_md.stdout
    assert "Status:" in out and "paused" in out
    assert "awaiting approval ship" in out or "ship" in out
    assert f"replayt resume TARGET {run_id} --approval ship" in out


def test_cli_inspect_unknown_run_id_shows_runs_hint(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["inspect", "00000000-0000-0000-0000-000000000000", "--log-dir", str(tmp_path)])
    assert r.exit_code == 1
    out = (r.stdout or "") + (r.stderr or "")
    assert "No events for run_id=" in out
    assert "Hint:" in out
    assert "replayt runs --limit 10" in out
    assert f"--log-dir {tmp_path}" in out


def test_cli_inspect_unknown_run_default_log_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["inspect", "00000000-0000-0000-0000-000000000000"])
    assert r.exit_code == 1
    out = (r.stdout or "") + (r.stderr or "")
    assert "replayt runs --limit 10" in out
    assert "--log-dir" not in out


def test_cli_replay_unknown_run_id_shows_runs_hint(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["replay", "not-a-real-id", "--log-dir", str(tmp_path)])
    assert r.exit_code == 1
    out = (r.stdout or "") + (r.stderr or "")
    assert "Hint:" in out
    assert f"--log-dir {tmp_path}" in out


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


def test_cli_inspect_print_inputs_round_trip(tmp_path: Path) -> None:
    runner = CliRunner()
    inputs_obj = {"issue": {"title": "Bug", "body": "too short"}}
    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.issue_triage:wf",
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            json.dumps(inputs_obj),
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    dumped = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--print-inputs"])
    assert dumped.exit_code == 0
    assert json.loads(dumped.stdout) == inputs_obj

    bad = runner.invoke(
        app,
        ["inspect", run_id, "--log-dir", str(tmp_path), "--print-inputs", "--output", "json"],
    )
    assert bad.exit_code != 0
    assert "--print-inputs" in (bad.stdout or "") + (bad.stderr or "")


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


def test_cli_module_target_import_error_onboarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "replayt_onb_importfail_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        'raise ImportError("replayt_onb_importfail_marker")\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "replayt_onb_importfail_pkg:wf", "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "replayt_onb_importfail_marker" in out
    assert "did not finish" in out.lower() or "circular import" in out.lower()
    assert "python -c" in out
    assert "doctor" in out.lower()


def test_cli_module_target_syntax_error_onboarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "replayt_onb_syntaxfail_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def broken(\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "replayt_onb_syntaxfail_pkg:wf", "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "syntax error" in out.lower()
    assert "py_compile" in out
    assert "doctor" in out.lower()


def test_cli_module_target_wrong_type_onboarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "replayt_onb_wrongtype_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("wf = 123\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "replayt_onb_wrongtype_pkg:wf", "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "not replayt.workflow.Workflow" in out
    assert "int" in out
    assert "doctor" in out.lower()


def test_cli_yaml_target_missing_pyyaml_onboarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_path = tmp_path / "mini_flow.yaml"
    workflow_path.write_text("name: x\nversion: 1\ninitial: start\nsteps:\n  start: {}\n", encoding="utf-8")

    def _boom(_path: object) -> dict[str, object]:
        raise RuntimeError("Install replayt with the `yaml` extra: pip install replayt[yaml]")

    monkeypatch.setattr("replayt.cli.targets.load_workflow_yaml", _boom)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "pip install replayt[yaml]" in out
    assert "replayt run" in out


def test_cli_run_resolves_target_from_replayt_target_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("REPLAYT_TARGET", str(workflow_path))
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--log-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "workflow=mini@1" in result.stdout


def test_cli_run_explicit_target_overrides_replayt_target_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_a = tmp_path / "flow_a.py"
    wf_a.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("flow_a")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    wf_b = tmp_path / "flow_b.py"
    wf_b.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("flow_b")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_TARGET", str(wf_a))
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(wf_b), "--log-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "workflow=flow_b@1" in result.stdout


def test_cli_run_resolves_target_from_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_path = tmp_path / "mini_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("mini")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[tool.replayt]\ntarget = "{workflow_path.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_TARGET", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--log-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "workflow=mini@1" in result.stdout


def test_cli_run_missing_target_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_TARGET", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--log-dir", str(tmp_path), "--dry-check"])
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "REPLAYT_TARGET" in out


def test_cli_config_json_reports_default_target_from_env_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_path = tmp_path / "w.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("w")
wf.set_initial("s")
@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[tool.replayt]\ntarget = "{workflow_path.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r1 = runner.invoke(app, ["config", "--format", "json"])
    assert r1.exit_code == 0
    d1 = json.loads(r1.stdout)
    assert Path(d1["run"]["default_target"]).resolve() == workflow_path.resolve()
    assert d1["run"]["default_target_source"] == "project_config:target"

    monkeypatch.setenv("REPLAYT_TARGET", "other_mod:wf")
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)
    r2 = runner.invoke(app, ["config", "--format", "json"])
    assert r2.exit_code == 0
    d2 = json.loads(r2.stdout)
    assert d2["run"]["default_target"] == "other_mod:wf"
    assert d2["run"]["default_target_source"] == "env:REPLAYT_TARGET"


def test_cli_run_resolves_inputs_from_replayt_inputs_file_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text('{"seed": 7}', encoding="utf-8")
    workflow_path = tmp_path / "seed_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("seed_flow")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    assert ctx.get("seed") == 7
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(inputs_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_TARGET", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "workflow=seed_flow@1" in result.stdout


def test_cli_run_explicit_inputs_json_overrides_replayt_inputs_file_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_inputs = tmp_path / "env_inputs.json"
    env_inputs.write_text('{"seed": 1}', encoding="utf-8")
    workflow_path = tmp_path / "seed_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("seed_flow")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    assert ctx.get("seed") == 2
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(env_inputs))
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            str(workflow_path),
            "--log-dir",
            str(tmp_path),
            "--dry-run",
            "--inputs-json",
            '{"seed": 2}',
        ],
    )
    assert result.exit_code == 0


def test_cli_run_inputs_file_env_overrides_pyproject_inputs_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cfg_inputs.json").write_text('{"seed": 1}', encoding="utf-8")
    (tmp_path / "env_inputs.json").write_text('{"seed": 2}', encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\ninputs_file = "cfg_inputs.json"\n', encoding="utf-8")
    workflow_path = tmp_path / "seed_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("seed_flow")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    assert ctx.get("seed") == 2
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(tmp_path / "env_inputs.json"))
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0


def test_cli_validate_uses_replayt_inputs_file_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text('{"x": 1}', encoding="utf-8")
    workflow_path = tmp_path / "v.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("s")
@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(inputs_path))
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["validate", str(workflow_path), "--format", "json"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["ok"] is True


def test_cli_run_missing_project_inputs_file_includes_onboarding_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\ninputs_file = "missing.json"\n', encoding="utf-8")
    workflow_path = tmp_path / "v.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("s")
@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("REPLAYT_INPUTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-check"])
    assert result.exit_code != 0
    err = _strip_ansi((result.stderr or "") + (result.stdout or ""))
    assert "[tool.replayt] inputs_file" in err
    assert "replayt config" in err


def test_cli_run_missing_env_inputs_file_includes_replayt_inputs_file_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_path = tmp_path / "v.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("s")
@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(tmp_path / "env_missing.json"))
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path), "--dry-check"])
    assert result.exit_code != 0
    err = _strip_ansi((result.stderr or "") + (result.stdout or ""))
    assert "REPLAYT_INPUTS_FILE" in err


def test_cli_run_missing_explicit_inputs_file_mentions_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_path = tmp_path / "v.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("s")
@wf.step("s")
def s(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("REPLAYT_INPUTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            str(workflow_path),
            "--log-dir",
            str(tmp_path),
            "--dry-check",
            "--inputs-file",
            str(tmp_path / "not_there.json"),
        ],
    )
    assert result.exit_code != 0
    err = _strip_ansi((result.stderr or "") + (result.stdout or ""))
    assert "current working directory" in err


def test_cli_config_json_reports_default_inputs_file_from_env_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_inp = tmp_path / "cfg.json"
    cfg_inp.write_text("{}", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[tool.replayt]\ninputs_file = "{cfg_inp.name}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("REPLAYT_INPUTS_FILE", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r1 = runner.invoke(app, ["config", "--format", "json"])
    assert r1.exit_code == 0
    d1 = json.loads(r1.stdout)
    assert Path(d1["run"]["default_inputs_file"]).resolve() == cfg_inp.resolve()
    assert d1["run"]["default_inputs_file_source"] == "project_config:inputs_file"

    env_inp = tmp_path / "env.json"
    env_inp.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", str(env_inp))
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)
    r2 = runner.invoke(app, ["config", "--format", "json"])
    assert r2.exit_code == 0
    d2 = json.loads(r2.stdout)
    assert Path(d2["run"]["default_inputs_file"]).resolve() == env_inp.resolve()
    assert d2["run"]["default_inputs_file_source"] == "env:REPLAYT_INPUTS_FILE"


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
    data = json.loads(result.stdout)
    assert data["schema"] == "replayt.run_result.v1"
    assert data["status"] == "completed"
    assert data["run_id"]


def test_cli_run_dry_run_json_output_is_machine_readable(tmp_path: Path) -> None:
    workflow_path = tmp_path / "json_dry_run_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("json_dry_run")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
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
            "--dry-run",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema"] == "replayt.run_result.v1"
    assert data["status"] == "completed"
    assert data["workflow"] == "json_dry_run@1"


def test_cli_init_scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r.exit_code == 0
    assert (tmp_path / "workflow.py").is_file()
    assert (tmp_path / ".env.example").is_file()
    inputs_file = tmp_path / "inputs.example.json"
    assert inputs_file.is_file()
    assert json.loads(inputs_file.read_text(encoding="utf-8")) == {"customer_name": "Sam"}
    config_file = tmp_path / ".replaytrc.toml"
    assert config_file.is_file()
    config_text = config_file.read_text(encoding="utf-8")
    assert 'target = "workflow.py"' in config_text
    assert 'inputs_file = "inputs.example.json"' in config_text
    gi = tmp_path / ".gitignore"
    assert gi.is_file()
    assert ".replayt/" in gi.read_text(encoding="utf-8")
    assert "PowerShell: .\\.venv\\Scripts\\Activate.ps1" in r.stdout
    assert "replayt doctor --skip-connectivity --target workflow.py" in r.stdout
    assert "replayt run --dry-check" in r.stdout
    assert "replayt run\n" in r.stdout or "replayt run\r\n" in r.stdout

    monkeypatch.chdir(tmp_path)
    _reset_project_config_cache()
    run = runner.invoke(app, ["run"])
    assert run.exit_code == 0
    assert "workflow=my_workflow@1" in run.stdout

    r2 = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r2.exit_code == 1
    r3 = runner.invoke(app, ["init", "--path", str(tmp_path), "--force"])
    assert r3.exit_code == 0


def test_cli_init_list_text() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--list"])
    assert r.exit_code == 0
    assert "Init templates:" in r.stdout
    assert "  - basic:" in r.stdout
    assert "replayt init --template basic" in r.stdout
    assert "issue-triage" in r.stdout
    assert "replayt init --template issue-triage" in r.stdout


def test_cli_init_list_json() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--list", "--output", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["schema"] == "replayt.init_templates.v1"
    keys = {t["key"] for t in data["templates"]}
    assert keys == {
        "approval",
        "basic",
        "issue-triage",
        "publishing-preflight",
        "tool-using",
        "yaml",
    }
    basic = next(t for t in data["templates"] if t["key"] == "basic")
    assert basic["workflow_file"] == "workflow.py"
    assert basic["inputs_file"] == "inputs.example.json"
    assert basic["llm_backed"] is False
    assert basic["summary"]
    assert basic["cli"]["init_here"] == "replayt init --template basic"
    assert basic["cli"]["init_with_ci_github"] == "replayt init --template basic --ci github"


def test_cli_init_list_rejects_ci_combo() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--list", "--ci", "github"])
    assert r.exit_code != 0
    assert "Cannot combine" in (r.stdout + r.stderr)


@pytest.mark.parametrize(
    ("template", "expected_inputs", "expected_snippet"),
    [
        (
            "issue-triage",
            {
                "issue": {
                    "title": "Crash on save",
                    "body": "Open app, click save, stack trace appears, expected file write.",
                }
            },
            "class TriageDecision",
        ),
        (
            "publishing-preflight",
            {"draft": "We guarantee 200% returns forever.", "audience": "general"},
            "ctx.request_approval(",
        ),
    ],
)
def test_cli_init_scaffold_richer_templates(
    tmp_path: Path,
    template: str,
    expected_inputs: dict[str, object],
    expected_snippet: str,
) -> None:
    runner = CliRunner()
    target_dir = tmp_path / template
    r = runner.invoke(app, ["init", "--path", str(target_dir), "--template", template])
    assert r.exit_code == 0
    wf_file = target_dir / "workflow.py"
    inputs_file = target_dir / "inputs.example.json"
    assert wf_file.is_file()
    assert inputs_file.is_file()
    assert (target_dir / ".replaytrc.toml").is_file()
    assert json.loads(inputs_file.read_text(encoding="utf-8")) == expected_inputs
    assert expected_snippet in wf_file.read_text(encoding="utf-8")
    assert "replayt run --dry-run" in r.stdout

    dry_check = runner.invoke(
        app,
        ["run", str(wf_file), "--dry-check", "--inputs-json", f"@{inputs_file}"],
    )
    assert dry_check.exit_code == 0
    assert "dry check passed" in dry_check.stdout


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


def test_cli_seal_rejects_invalid_run_id(tmp_path: Path) -> None:
    runner = CliRunner()
    bad = "../../etc/passwd"
    r = runner.invoke(app, ["seal", bad, "--log-dir", str(tmp_path)])
    assert r.exit_code == 1
    assert "run_id must be" in r.stderr or "run_id must be" in r.stdout


def test_cli_verify_seal_succeeds_after_seal(tmp_path: Path) -> None:
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
    ok = runner.invoke(app, ["verify-seal", run_id, "--log-dir", str(tmp_path)])
    assert ok.exit_code == 0
    assert "OK:" in ok.stdout
    js = runner.invoke(
        app,
        ["verify-seal", run_id, "--log-dir", str(tmp_path), "--output", "json"],
    )
    assert js.exit_code == 0
    payload = json.loads(js.stdout)
    assert payload["schema"] == "replayt.verify_seal_report.v1"
    assert payload["ok"] is True
    assert payload["mismatches"] == []


def test_cli_verify_seal_detects_tampered_jsonl(tmp_path: Path) -> None:
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
    assert runner.invoke(app, ["seal", run_id, "--log-dir", str(tmp_path)]).exit_code == 0
    log_path = tmp_path / f"{run_id}.jsonl"
    log_path.write_bytes(log_path.read_bytes() + b"\n# tamper\n")
    bad = runner.invoke(app, ["verify-seal", run_id, "--log-dir", str(tmp_path)])
    assert bad.exit_code == 1
    assert "MISMATCH" in bad.stderr or "MISMATCH" in bad.stdout
    js = runner.invoke(
        app,
        ["verify-seal", run_id, "--log-dir", str(tmp_path), "--output", "json"],
    )
    assert js.exit_code == 1
    payload = json.loads(js.stdout)
    assert payload["ok"] is False
    assert payload["mismatches"]


def test_cli_verify_seal_hook_failure_aborts_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = json.dumps(sys.executable)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nverify_seal_hook = [{exe}, \"-c\", \"import sys; sys.exit(9)\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    assert runner.invoke(app, ["seal", rid, "--log-dir", str(tmp_path)]).exit_code == 0
    verify = runner.invoke(app, ["verify-seal", rid, "--log-dir", str(tmp_path)])
    assert verify.exit_code == 1
    assert "verify_seal_hook" in (verify.stdout + verify.stderr).lower()


def test_cli_verify_seal_hook_receives_policy_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook_out = tmp_path / "verify_seal_hook.json"
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "Path(os.environ['HOOK_OUT']).write_text("
        "json.dumps({"
        "'run_id': os.environ.get('REPLAYT_RUN_ID'), "
        "'log_dir': os.environ.get('REPLAYT_LOG_DIR'), "
        "'manifest': os.environ.get('REPLAYT_VERIFY_SEAL_MANIFEST'), "
        "'jsonl': os.environ.get('REPLAYT_VERIFY_SEAL_JSONL'), "
        "'schema': os.environ.get('REPLAYT_VERIFY_SEAL_SCHEMA'), "
        "'line_count': os.environ.get('REPLAYT_VERIFY_SEAL_LINE_COUNT'), "
        "'file_sha256': os.environ.get('REPLAYT_VERIFY_SEAL_FILE_SHA256'), "
        "'workflow_contract_sha256': os.environ.get('REPLAYT_WORKFLOW_CONTRACT_SHA256'), "
        "'workflow_name': os.environ.get('REPLAYT_WORKFLOW_NAME'), "
        "'workflow_version': os.environ.get('REPLAYT_WORKFLOW_VERSION'), "
        "'metadata': (json.loads(os.environ['REPLAYT_RUN_METADATA_JSON']) "
        "if os.environ.get('REPLAYT_RUN_METADATA_JSON') else None), "
        "'tags': (json.loads(os.environ['REPLAYT_RUN_TAGS_JSON']) "
        "if os.environ.get('REPLAYT_RUN_TAGS_JSON') else None), "
        "'experiment': (json.loads(os.environ['REPLAYT_RUN_EXPERIMENT_JSON']) "
        "if os.environ.get('REPLAYT_RUN_EXPERIMENT_JSON') else None)"
        "}), encoding='utf-8')"
    )
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nverify_seal_hook = [{json.dumps(sys.executable)}, \"-c\", {json.dumps(script)}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOOK_OUT", str(hook_out))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
            '{"change_ticket":"CHG-77"}',
            "--tag",
            "verify=post",
            "--experiment-json",
            '{"audit":"seal_ok"}',
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    manifest_path = (tmp_path / f"{rid}.seal.json").resolve()
    jsonl_path = (tmp_path / f"{rid}.jsonl").resolve()
    assert runner.invoke(app, ["seal", rid, "--log-dir", str(tmp_path)]).exit_code == 0
    verify = runner.invoke(app, ["verify-seal", rid, "--log-dir", str(tmp_path)])
    assert verify.exit_code == 0
    data = json.loads(hook_out.read_text(encoding="utf-8"))
    assert data["run_id"] == rid
    assert data["log_dir"] == str(tmp_path.resolve())
    assert data["manifest"] == str(manifest_path)
    assert data["jsonl"] == str(jsonl_path)
    assert data["schema"] == "replayt.seal.v1"
    assert int(data["line_count"]) > 0
    assert isinstance(data["file_sha256"], str) and len(data["file_sha256"]) == 64
    assert data["workflow_name"] == "hello_world_tutorial"
    assert data["workflow_version"] == "1"
    assert isinstance(data["workflow_contract_sha256"], str) and len(data["workflow_contract_sha256"]) == 64
    assert data["metadata"] == {"change_ticket": "CHG-77"}
    assert data["tags"] == {"verify": "post"}
    assert data["experiment"] == {"audit": "seal_ok"}


def test_cli_verify_seal_export_manifest_with_jsonl_override(tmp_path: Path) -> None:
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
    out_tar = tmp_path / "exp.tar.gz"
    be = runner.invoke(
        app,
        ["bundle-export", run_id, "--out", str(out_tar), "--log-dir", str(tmp_path), "--seal"],
    )
    assert be.exit_code == 0
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    with tarfile.open(out_tar, "r:gz") as tf:
        tf.extractall(extract_dir, filter="data")
    prefix = next(p for p in extract_dir.iterdir() if p.is_dir())
    seal_path = prefix / "events.seal.json"
    jsonl_path = prefix / "events.jsonl"
    assert seal_path.is_file() and jsonl_path.is_file()
    v = runner.invoke(
        app,
        [
            "verify-seal",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--manifest",
            str(seal_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert v.exit_code == 0


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


def test_cli_try_input_override_merges_with_packaged_defaults(tmp_path: Path) -> None:
    runner = CliRunner()
    run = runner.invoke(
        app,
        ["try", "--log-dir", str(tmp_path), "--input", "customer_name=Pat"],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "json"])
    assert inspect.exit_code == 0
    payload = json.loads(inspect.stdout)
    assert payload["schema"] == "replayt.inspect_report.v1"
    assert payload["run_id"] == run_id
    started = next(event for event in payload["events"] if event["type"] == "run_started")
    assert started["payload"]["inputs"] == {"customer_name": "Pat"}


def test_cli_try_lists_packaged_examples() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--list"])
    assert r.exit_code == 0
    assert "hello-world" in r.stdout
    assert "issue-triage" in r.stdout
    assert "publishing-preflight" in r.stdout
    assert "replayt try --example hello-world" in r.stdout


def test_cli_try_list_json_includes_cli_snippets() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--list", "--output", "json"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert payload["schema"] == "replayt.try_examples.v1"
    by_key = {ex["key"]: ex for ex in payload["examples"]}
    hello = by_key["hello-world"]
    cli = hello["cli"]
    assert cli["try_offline"] == "replayt try --example hello-world"
    assert cli["try_live"] == "replayt try --example hello-world --live"
    assert cli["try_dry_check"] == "replayt try --example hello-world --dry-check"
    assert cli["copy_to_dot"] == "replayt try --example hello-world --copy-to ."
    triage = by_key["issue-triage"]
    assert triage["cli"]["try_offline"] == "replayt try --example issue-triage"


def test_cli_try_copy_to_writes_workflow_and_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "flow"
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--example", "hello-world", "--copy-to", str(dest)])
    assert r.exit_code == 0
    wf = dest / "workflow.py"
    inputs_f = dest / "inputs.example.json"
    config_file = dest / ".replaytrc.toml"
    assert wf.is_file()
    assert inputs_f.is_file()
    assert config_file.is_file()
    assert "Workflow" in wf.read_text(encoding="utf-8")
    loaded = json.loads(inputs_f.read_text(encoding="utf-8"))
    assert loaded.get("customer_name") == "Sam"
    assert "Next steps:" in r.stdout
    assert str(wf) in r.stdout
    assert "replayt doctor --skip-connectivity --target workflow.py" in r.stdout
    assert "replayt run --dry-check" in r.stdout
    assert "replayt run\n" in r.stdout or "replayt run\r\n" in r.stdout

    monkeypatch.chdir(dest)
    _reset_project_config_cache()
    run = runner.invoke(app, ["run"])
    assert run.exit_code == 0
    assert "workflow=hello_world_tutorial@1" in run.stdout


def test_cli_try_copy_to_json_schema(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["try", "--example", "hello-world", "--copy-to", str(dest), "--output", "json"],
    )
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert payload["schema"] == "replayt.try_copy.v1"
    assert payload["example"] == "hello-world"
    assert payload["target"] == "replayt_examples.e01_hello_world:wf"
    assert Path(payload["workflow_py"]).is_file()
    assert Path(payload["inputs_example_json"]).is_file()
    assert Path(payload["project_config"]).is_file()


def test_cli_try_copy_to_refuses_overwrite_without_force(tmp_path: Path) -> None:
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "workflow.py").write_text("x", encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--copy-to", str(dest)])
    assert r.exit_code == 1
    assert "Refusing to overwrite" in (r.stderr or "")


def test_cli_try_copy_to_force_overwrites(tmp_path: Path) -> None:
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "workflow.py").write_text("stale", encoding="utf-8")
    (dest / "inputs.example.json").write_text("{}", encoding="utf-8")
    (dest / ".replaytrc.toml").write_text('target = "stale.py"\n', encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--copy-to", str(dest), "--force"])
    assert r.exit_code == 0
    assert "Workflow" in (dest / "workflow.py").read_text(encoding="utf-8")
    assert 'target = "workflow.py"' in (dest / ".replaytrc.toml").read_text(encoding="utf-8")


def test_cli_try_copy_to_llm_backed_example_suggests_dry_run(tmp_path: Path) -> None:
    dest = tmp_path / "triage"
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--example", "issue-triage", "--copy-to", str(dest)])
    assert r.exit_code == 0
    assert "replayt run --dry-run" in r.stdout
    assert "replayt run\n" in r.stdout or "replayt run\r\n" in r.stdout


def test_cli_try_copy_to_rejects_live_and_inputs(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["try", "--copy-to", str(tmp_path), "--live"])
    assert r.exit_code == 2
    assert "Cannot combine --copy-to" in (r.stderr or r.stdout or "")

    r2 = runner.invoke(app, ["try", "--copy-to", str(tmp_path), "--input", "customer_name=Pat"])
    assert r2.exit_code == 2
    assert "Cannot combine --copy-to" in (r2.stderr or r2.stdout or "")


def test_cli_try_runs_selected_example_with_inputs_file_override(tmp_path: Path) -> None:
    inputs_file = tmp_path / "issue_inputs.json"
    inputs_file.write_text(
        json.dumps(
            {
                "issue": {
                    "title": "Checkout bug on mobile",
                    "body": "Customer reports checkout fails after tapping Pay on iOS Safari with a white screen.",
                }
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "try",
            "--example",
            "issue-triage",
            "--inputs-file",
            str(inputs_file),
            "--log-dir",
            str(tmp_path),
        ],
    )
    assert run.exit_code == 0
    assert "workflow=github_issue_triage" in run.stdout
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "json"])
    assert inspect.exit_code == 0
    payload = json.loads(inspect.stdout)
    assert payload["schema"] == "replayt.inspect_report.v1"
    assert payload["run_id"] == run_id
    started = next(event for event in payload["events"] if event["type"] == "run_started")
    assert started["payload"]["workflow_name"] == "github_issue_triage"
    assert started["payload"]["inputs"]["issue"]["title"] == "Checkout bug on mobile"


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
    assert "attention=" not in report.stdout


def test_cli_report_html_header_includes_attention_kv(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs_html_attn"
    log_dir.mkdir()
    run_id = "pause-html-attn"
    events = [
        {
            "ts": "2026-03-21T11:00:00+00:00",
            "run_id": run_id,
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "gate", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-21T11:00:01+00:00",
            "run_id": run_id,
            "seq": 2,
            "type": "run_paused",
            "payload": {},
        },
        {
            "ts": "2026-03-21T11:00:02+00:00",
            "run_id": run_id,
            "seq": 3,
            "type": "approval_requested",
            "payload": {
                "approval_id": "go",
                "state": "review",
                "summary": "OK?",
                "details": {},
            },
        },
    ]
    (log_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(app, ["report", run_id, "--log-dir", str(log_dir), "--style", "stakeholder"])
    assert r.exit_code == 0
    assert "attention=" in r.stdout
    assert "awaiting approval go" in r.stdout


def test_cli_report_support_style_surfaces_failure_context(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_id = "support-fail"
    events = [
        {
            "ts": "2026-03-21T10:00:00+00:00",
            "run_id": run_id,
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "support_flow",
                "workflow_version": "7",
                "run_metadata": {"tenant": "acme", "feature_flag": "beta"},
                "experiment": {"lane": "b"},
                "workflow_meta": {"surface": "ops"},
            },
        },
        {
            "ts": "2026-03-21T10:00:01+00:00",
            "run_id": run_id,
            "seq": 2,
            "type": "state_entered",
            "payload": {"state": "classify"},
        },
        {
            "ts": "2026-03-21T10:00:02+00:00",
            "run_id": run_id,
            "seq": 3,
            "type": "retry_scheduled",
            "payload": {
                "state": "classify",
                "attempt": 1,
                "max_attempts": 3,
                "error": {"type": "TimeoutError", "message": "upstream timed out"},
            },
        },
        {
            "ts": "2026-03-21T10:00:03+00:00",
            "run_id": run_id,
            "seq": 4,
            "type": "structured_output_failed",
            "payload": {
                "state": "classify",
                "schema_name": "Decision",
                "stage": "schema_validate",
                "structured_output_mode": "prompt_only",
                "error": {"type": "ValidationError", "message": "field required"},
            },
        },
        {
            "ts": "2026-03-21T10:00:04+00:00",
            "run_id": run_id,
            "seq": 5,
            "type": "run_failed",
            "payload": {
                "state": "classify",
                "error": {"type": "RuntimeError", "message": "ticket could not be routed"},
            },
        },
        {
            "ts": "2026-03-21T10:00:05+00:00",
            "run_id": run_id,
            "seq": 6,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    (log_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    report = runner.invoke(app, ["report", run_id, "--log-dir", str(log_dir), "--style", "support"])

    assert report.exit_code == 0
    assert "Support handoff" in report.stdout
    assert "Run failed" in report.stdout
    assert "Latest structured parse failure" in report.stdout
    assert "Retries happened during this run" in report.stdout
    assert "feature_flag" in report.stdout
    assert "lane" in report.stdout
    assert "Token Usage" not in report.stdout


def test_cli_report_markdown_support_style_is_plaintext_handoff(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_id = "support-md"
    events = [
        {
            "ts": "2026-03-21T10:00:00+00:00",
            "run_id": run_id,
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "support_flow",
                "workflow_version": "7",
                "run_metadata": {"tenant": "acme", "feature_flag": "beta"},
                "experiment": {"lane": "b"},
                "workflow_meta": {"surface": "ops"},
            },
        },
        {
            "ts": "2026-03-21T10:00:01+00:00",
            "run_id": run_id,
            "seq": 2,
            "type": "state_entered",
            "payload": {"state": "classify"},
        },
        {
            "ts": "2026-03-21T10:00:02+00:00",
            "run_id": run_id,
            "seq": 3,
            "type": "retry_scheduled",
            "payload": {
                "state": "classify",
                "attempt": 1,
                "max_attempts": 3,
                "error": {"type": "TimeoutError", "message": "upstream timed out"},
            },
        },
        {
            "ts": "2026-03-21T10:00:03+00:00",
            "run_id": run_id,
            "seq": 4,
            "type": "structured_output_failed",
            "payload": {
                "state": "classify",
                "schema_name": "Decision",
                "stage": "schema_validate",
                "structured_output_mode": "prompt_only",
                "error": {"type": "ValidationError", "message": "field required"},
            },
        },
        {
            "ts": "2026-03-21T10:00:04+00:00",
            "run_id": run_id,
            "seq": 5,
            "type": "run_failed",
            "payload": {
                "state": "classify",
                "error": {"type": "RuntimeError", "message": "ticket could not be routed"},
            },
        },
        {
            "ts": "2026-03-21T10:00:05+00:00",
            "run_id": run_id,
            "seq": 6,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    (log_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    report = runner.invoke(
        app,
        ["report", run_id, "--log-dir", str(log_dir), "--style", "support", "--format", "markdown"],
    )

    assert report.exit_code == 0
    out = report.stdout
    assert "<!DOCTYPE" not in out
    assert "<html" not in out
    assert "# Support handoff" in out
    assert "## Support summary" in out
    assert "### Run failed" in out
    assert "### Latest structured parse failure" in out
    assert "### Retries happened during this run" in out
    assert "feature_flag" in out
    assert "lane" in out
    assert "## Token usage" not in out
    assert "--format html --style default" in out
    assert "**attention=**" in out
    assert "failed in classify" in out


def test_cli_report_markdown_paused_includes_resume_hint(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs_md_pause"
    log_dir.mkdir()
    run_id = "pause-md"
    events = [
        {
            "ts": "2026-03-21T11:00:00+00:00",
            "run_id": run_id,
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "gate", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-21T11:00:01+00:00",
            "run_id": run_id,
            "seq": 2,
            "type": "run_paused",
            "payload": {},
        },
        {
            "ts": "2026-03-21T11:00:02+00:00",
            "run_id": run_id,
            "seq": 3,
            "type": "approval_requested",
            "payload": {
                "approval_id": "ship-it",
                "state": "review",
                "summary": "Ready?",
                "details": {},
            },
        },
    ]
    (log_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["report", run_id, "--log-dir", str(log_dir), "--format", "markdown", "--style", "stakeholder"],
    )
    assert r.exit_code == 0
    assert "replayt resume TARGET" in r.stdout
    assert "ship-it" in r.stdout
    assert "**attention=**" in r.stdout
    assert "awaiting approval ship-it" in r.stdout


def test_cli_replay_and_report_surface_step_notes(tmp_path: Path) -> None:
    workflow_path = tmp_path / "framework_notes.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("framework_notes")
wf.set_initial("compose")

@wf.step("compose")
def compose(ctx):
    ctx.note(
        "framework_summary",
        summary="sandbox graph completed",
        data={"provider": "langgraph", "loop_count": 2},
    )
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    run = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    replay = runner.invoke(app, ["replay", run_id, "--log-dir", str(tmp_path)])
    assert replay.exit_code == 0
    assert "step_note" in replay.stdout
    assert '"kind": "framework_summary"' in replay.stdout

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path), "--output", "json"])
    assert inspect.exit_code == 0
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["summary"]["notes"] == 1

    inspect_notes = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--output",
            "json",
            "--event-type",
            "step_note",
        ],
    )
    assert inspect_notes.exit_code == 0
    notes_payload = json.loads(inspect_notes.stdout)
    assert notes_payload["schema"] == "replayt.inspect_report.v1"
    assert notes_payload["event_type_filter"] == ["step_note"]
    assert [e["type"] for e in notes_payload["events"]] == ["step_note"]
    assert notes_payload["summary"]["notes"] == 1

    inspect_note_kind = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--output",
            "json",
            "--note-kind",
            "framework_summary",
        ],
    )
    assert inspect_note_kind.exit_code == 0
    note_kind_payload = json.loads(inspect_note_kind.stdout)
    assert note_kind_payload["schema"] == "replayt.inspect_report.v1"
    assert note_kind_payload["note_kind_filter"] == ["framework_summary"]
    assert [e["type"] for e in note_kind_payload["events"]] == ["step_note"]
    assert note_kind_payload["events"][0]["payload"]["kind"] == "framework_summary"

    inspect_or = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--output",
            "json",
            "--event-type",
            "step_note",
            "--event-type",
            "run_started",
        ],
    )
    assert inspect_or.exit_code == 0
    or_payload = json.loads(inspect_or.stdout)
    assert or_payload["schema"] == "replayt.inspect_report.v1"
    assert set(or_payload["event_type_filter"]) == {"run_started", "step_note"}
    assert {e["type"] for e in or_payload["events"]} <= {"run_started", "step_note"}
    assert len(or_payload["events"]) >= 2

    inspect_or_note_kind = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--log-dir",
            str(tmp_path),
            "--output",
            "json",
            "--event-type",
            "step_note",
            "--event-type",
            "run_started",
            "--note-kind",
            "framework_summary",
        ],
    )
    assert inspect_or_note_kind.exit_code == 0
    or_note_kind_payload = json.loads(inspect_or_note_kind.stdout)
    assert or_note_kind_payload["schema"] == "replayt.inspect_report.v1"
    assert set(or_note_kind_payload["event_type_filter"]) == {"run_started", "step_note"}
    assert or_note_kind_payload["note_kind_filter"] == ["framework_summary"]
    assert {e["type"] for e in or_note_kind_payload["events"]} == {"run_started", "step_note"}

    inspect_text = runner.invoke(
        app,
        ["inspect", run_id, "--log-dir", str(tmp_path), "--note-kind", "framework_summary"],
    )
    assert inspect_text.exit_code == 0
    assert "shown=1" in inspect_text.stdout
    assert inspect_text.stdout.count("step_note") >= 1

    report = runner.invoke(app, ["report", run_id, "--log-dir", str(tmp_path)])
    assert report.exit_code == 0
    assert "Step Notes" in report.stdout
    assert "framework_summary" in report.stdout
    assert "sandbox graph completed" in report.stdout


def test_cli_report_includes_approval_resolution_audit_fields(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_id = "approval-audit"
    events = [
        {
            "ts": "2026-03-21T11:00:00+00:00",
            "run_id": run_id,
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "approval_flow", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-21T11:00:01+00:00",
            "run_id": run_id,
            "seq": 2,
            "type": "approval_requested",
            "payload": {
                "approval_id": "ship",
                "state": "review",
                "summary": "Ship the launch email?",
                "details": {"ticket_id": "CHG-42"},
                "on_approve": "done",
                "on_reject": "abort",
            },
        },
        {
            "ts": "2026-03-21T11:00:02+00:00",
            "run_id": run_id,
            "seq": 3,
            "type": "approval_resolved",
            "payload": {
                "approval_id": "ship",
                "approved": True,
                "resolver": "bridge",
                "reason": "CAB approved",
                "actor": {"email": "pm@example.com", "ticket_id": "CHG-42"},
            },
        },
        {
            "ts": "2026-03-21T11:00:03+00:00",
            "run_id": run_id,
            "seq": 4,
            "type": "approval_applied",
            "payload": {"approval_state": "review", "resumed_at_state": "done"},
        },
        {
            "ts": "2026-03-21T11:00:04+00:00",
            "run_id": run_id,
            "seq": 5,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    report = runner.invoke(app, ["report", run_id, "--log-dir", str(log_dir)])

    assert report.exit_code == 0
    assert "Resolver:</span> bridge" in report.stdout
    assert "Reason:</span> CAB approved" in report.stdout
    assert "ticket_id" in report.stdout
    assert (
        "Resume path:</span> review -&gt; done" in report.stdout
        or "Resume path:</span> review -> done" in report.stdout
    )


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
    stats_payload = json.loads(stats.stdout)
    assert stats_payload["schema"] == "replayt.stats_report.v1"
    assert stats_payload["runs_included"] == 1
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    html_out = runner.invoke(
        app,
        ["replay", run_id, "--log-dir", str(tmp_path), "--format", "html"],
    )
    assert html_out.exit_code == 0
    assert "<style>" in html_out.stdout
    assert run_id in html_out.stdout


def test_cli_replay_stakeholder_html_uses_style(tmp_path: Path) -> None:
    workflow_path = tmp_path / "replay_style.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("replay_style_wf")
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
    html_out = runner.invoke(
        app,
        ["replay", run_id, "--log-dir", str(tmp_path), "--format", "html", "--style", "stakeholder"],
    )
    assert html_out.exit_code == 0
    assert "Run timeline" in html_out.stdout
    assert "--style default" in html_out.stdout


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


def test_cli_runs_orders_by_last_event_timestamp(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    old_lines = [
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "run_id": "zzz-old",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-01-01T00:01:00+00:00",
            "run_id": "zzz-old",
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    new_lines = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "aaa-new",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:01:00+00:00",
            "run_id": "aaa-new",
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / "zzz-old.jsonl").write_text("\n".join(json.dumps(x) for x in old_lines) + "\n", encoding="utf-8")
    (log_dir / "aaa-new.jsonl").write_text("\n".join(json.dumps(x) for x in new_lines) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--limit", "1"])
    assert result.exit_code == 0
    first_line = result.stdout.strip().splitlines()[0]
    assert first_line.startswith("aaa-new")


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


def test_cli_run_with_sqlite_closes_store_after_command(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite3"
    runner = CliRunner()

    run = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path / "jsonl"),
            "--sqlite",
            str(db_path),
            "--inputs-json",
            '{"customer_name":"Sam"}',
            "--dry-run",
        ],
    )

    assert run.exit_code == 0
    db_path.unlink()
    assert not db_path.exists()


def test_cli_resume_with_sqlite_closes_store_after_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    db_path = tmp_path / "events.sqlite3"
    runner = CliRunner()
    run = runner.invoke(
        app,
        ["run", "approval_flow:wf", "--log-dir", str(tmp_path / "jsonl"), "--sqlite", str(db_path)],
    )
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
            str(tmp_path / "jsonl"),
            "--sqlite",
            str(db_path),
        ],
    )

    assert resume.exit_code == 0
    db_path.unlink()
    assert not db_path.exists()


def test_cli_read_commands_reject_missing_sqlite_without_creating_database(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite3"
    runner = CliRunner()

    result = runner.invoke(app, ["runs", "--sqlite", str(missing_db)])

    assert result.exit_code == 1
    assert "sqlite store not found" in (result.stdout + result.stderr).lower()
    assert not missing_db.exists()


def test_cli_read_commands_do_not_create_missing_log_dir(tmp_path: Path) -> None:
    missing_log_dir = tmp_path / "missing-logs"
    runner = CliRunner()

    runs = runner.invoke(app, ["runs", "--log-dir", str(missing_log_dir)])
    stats = runner.invoke(app, ["stats", "--log-dir", str(missing_log_dir), "--output", "json"])

    assert runs.exit_code == 0
    assert "No runs found" in runs.stdout
    assert stats.exit_code == 0
    assert json.loads(stats.stdout)["runs_total_on_disk"] == 0
    assert not missing_log_dir.exists()


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

    cfg, cfg_path, unknown, shadowed = cfg_mod.get_project_config()
    assert cfg.get("log_dir") == ".logs/runs"
    assert cfg.get("log_mode") == "full"
    assert cfg.get("timeout") == 30
    assert cfg_path is not None
    assert "pyproject.toml" in cfg_path
    assert unknown == frozenset()
    assert shadowed == ()


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


def test_project_config_shadowed_pyproject_when_replaytrc_in_same_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".replaytrc.toml").write_text('log_dir = "from_rc"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\nlog_dir = "from_pyproject"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_SHADOWED_SOURCES", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    cfg, path, _unk, shadow = cfg_mod.get_project_config()
    assert cfg.get("log_dir") == "from_rc"
    assert Path(path or "").name == ".replaytrc.toml"
    assert shadow == (str((tmp_path / "pyproject.toml").resolve()),)

    runner = CliRunner()
    r = runner.invoke(app, ["config", "--format", "json"])
    assert r.exit_code == 0
    rep = json.loads(r.stdout)
    assert rep["project_config"]["shadowed_sources"] == [str((tmp_path / "pyproject.toml").resolve())]

    d = runner.invoke(app, ["doctor", "--format", "json", "--skip-connectivity"])
    assert d.exit_code == 0
    doc = json.loads(d.stdout)
    by_name = {c["name"]: c for c in doc["checks"]}
    assert by_name["project_config_shadowed_sources"]["ok"] is False


def test_cli_config_reports_effective_project_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.replayt]\nprovider = "openai"\nmodel = "gpt-4.1-mini"\nlog_mode = "full"\n'
        'run_hook_timeout = 30\nresume_hook_timeout = 45\nexport_hook_timeout = 33\nseal_hook_timeout = 40\n'
        "verify_seal_hook_timeout = 41\n"
        'redact_keys = ["email", "token"]\n'
        'approval_actor_required_keys = ["email", "ticket_id"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema"] == "replayt.config_report.v1"
    assert data["runtime_defaults"]["log_mode"] == "full"
    assert data["runtime_defaults"]["log_mode_source"] == "project_config:log_mode"
    assert data["runtime_defaults"]["redact_keys"] == ["email", "token"]
    assert data["runtime_defaults"]["redact_keys_source"] == "project_config:redact_keys"
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["provider_source"] == "project_config:provider"
    assert data["llm"]["model"] == "gpt-4.1-mini"
    assert data["llm"]["model_source"] == "project_config:model"
    assert data["llm"]["base_url"] == "https://api.openai.com/v1"
    assert data["run"]["hook_timeout_seconds"] == 30.0
    assert data["run"]["hook_timeout_source"] == "project_config:run_hook_timeout"
    assert data["resume"]["hook_timeout_seconds"] == 45.0
    assert data["export"]["hook_timeout_seconds"] == 33.0
    assert data["export"]["hook_timeout_source"] == "project_config:export_hook_timeout"
    assert data["seal"]["hook_timeout_seconds"] == 40.0
    assert data["seal"]["hook_timeout_source"] == "project_config:seal_hook_timeout"
    assert data["verify_seal"]["hook_timeout_seconds"] == 41.0
    assert data["verify_seal"]["hook_timeout_source"] == "project_config:verify_seal_hook_timeout"
    assert data["resume"]["required_actor_keys"] == ["email", "ticket_id"]
    assert data["resume"]["required_actor_keys_source"] == "project_config:approval_actor_required_keys"
    assert data["resume"]["required_reason"] is False
    assert data["resume"]["required_reason_source"] == "unset"
    assert any(check["name"] == "log_dir_ready" for check in data["filesystem"]["checks"])
    assert any(
        warning == "full log mode stores raw LLM request and response bodies on disk"
        for warning in data["trust_boundary"]["warnings"]
    )
    assert data["project_config"]["unknown_keys"] == []


def test_cli_config_reports_unknown_project_config_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.replayt]\nlog_dir = "my_logs"\n"log-mode" = "full"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["project_config"]["unknown_keys"] == ["log-mode"]
    assert data["paths"]["log_dir"].endswith("my_logs")

    text = runner.invoke(app, ["config", "--format", "text"])
    assert text.exit_code == 0
    assert "project_config_unknown_keys" in text.stdout
    assert "log-mode" in text.stdout


def test_cli_config_reports_ci_artifact_env_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junit = tmp_path / "artifacts" / "junit.xml"
    summary = tmp_path / "artifacts" / "summary.json"
    github = tmp_path / "artifacts" / "github.md"
    monkeypatch.setenv("REPLAYT_JUNIT_XML", str(junit))
    monkeypatch.setenv("REPLAYT_SUMMARY_JSON", str(summary))
    monkeypatch.setenv("REPLAYT_GITHUB_SUMMARY", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(github))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    ci_artifacts = data["ci_artifacts"]
    assert ci_artifacts["junit_xml"]["path"] == str(junit.resolve())
    assert ci_artifacts["junit_xml"]["source"] == "env:REPLAYT_JUNIT_XML"
    assert ci_artifacts["summary_json"]["path"] == str(summary.resolve())
    assert ci_artifacts["summary_json"]["source"] == "env:REPLAYT_SUMMARY_JSON"
    assert ci_artifacts["github_summary"]["requested"] is True
    assert ci_artifacts["github_summary"]["requested_source"] == "env:REPLAYT_GITHUB_SUMMARY"
    assert ci_artifacts["github_summary"]["path"] == str(github.resolve())
    assert ci_artifacts["github_summary"]["path_source"] == "env:GITHUB_STEP_SUMMARY"
    readiness = {check["name"]: check for check in data["filesystem"]["checks"]}
    assert readiness["ci_junit_xml_ready"]["ok"] is True
    assert readiness["ci_summary_json_ready"]["ok"] is True
    assert readiness["ci_github_summary_ready"]["ok"] is True


def test_cli_doctor_warns_on_unknown_project_config_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nlog_dir = "my_logs"\nunknown_flag = true\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--skip-connectivity"])
    assert result.exit_code == 0
    assert "project_config_unknown_keys" in result.stdout
    assert "unknown_flag" in result.stdout


def test_cli_min_replayt_version_blocks_non_bypass_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nmin_replayt_version = "999.0.0"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["graph", "replayt_examples.issue_triage:wf"])
    assert r.exit_code != 0
    out = (r.stdout or "") + (r.stderr or "")
    assert "min_replayt_version" in out or "999.0.0" in out


def test_cli_min_replayt_version_bypass_for_config_version_doctor_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nmin_replayt_version = "999.0.0"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["config", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["project_config"]["min_replayt_version"] == "999.0.0"
    assert data["project_config"]["min_replayt_version_satisfied"] is False

    r2 = runner.invoke(app, ["version"])
    assert r2.exit_code == 0

    r3 = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r3.exit_code == 1
    doc = json.loads(r3.stdout)
    chk = next(c for c in doc["checks"] if c["name"] == "project_config_min_replayt_version")
    assert chk["ok"] is False

    init_dir = tmp_path / "fresh_init"
    r4 = runner.invoke(app, ["init", "--path", str(init_dir)])
    assert r4.exit_code == 0


def test_cli_min_replayt_version_invalid_constraint_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.replayt]\nmin_replayt_version = "not-a-version"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["graph", "replayt_examples.issue_triage:wf"])
    assert r.exit_code != 0
    out = (r.stdout or "") + (r.stderr or "")
    assert "min_replayt_version" in out or "Invalid" in out


def test_cli_config_defaults_to_local_ollama_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", {})
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", frozenset())
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_SHADOWED_SOURCES", ())
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", str(Path.cwd().resolve()))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["project_config"]["shadowed_sources"] == []
    assert data["llm"]["provider"] == "ollama"
    assert data["llm"]["provider_source"] == "default:ollama"
    assert data["llm"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert data["llm"]["base_url_source"] == "provider_preset:ollama"
    assert data["llm"]["model"] == "llama3.2"
    assert data["llm"]["model_source"] == "provider_default:ollama"


def test_cli_run_uses_project_config_provider_and_model_in_runtime_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[tool.replayt]\nprovider = "openai"\nmodel = "gpt-4.1-mini"\n',
        encoding="utf-8",
    )
    workflow_path = repo / "cfg_runtime.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("cfg_runtime")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(repo)
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    log_dir = tmp_path / "logs"
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(log_dir)])

    assert result.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("run_id="))
    events = [
        json.loads(line)
        for line in (log_dir / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(event for event in events if event["type"] == "run_started")
    assert started["payload"]["runtime"]["llm"]["base_url"] == "https://api.openai.com/v1"
    assert started["payload"]["runtime"]["llm"]["model"] == "gpt-4.1-mini"


def test_resolve_log_dir_uses_project_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    worktree = repo / "pkg" / "cli"
    worktree.mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[tool.replayt]\nlog_dir = "logs"\n', encoding="utf-8")
    monkeypatch.chdir(worktree)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    assert cfg_mod.resolve_log_dir(cfg_mod.DEFAULT_LOG_DIR) == (repo / "logs").resolve()


def test_cli_run_uses_config_relative_log_dir_and_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    worktree = repo / "services" / "demo"
    worktree.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[tool.replayt]\nlog_dir = "logs"\nsqlite = "data/events.sqlite3"\n',
        encoding="utf-8",
    )
    wf_path = worktree / "cfg_flow.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("cfg_flow")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(worktree)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "cfg_flow.py", "--dry-run"])

    assert result.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("run_id="))
    assert (repo / "logs" / f"{run_id}.jsonl").is_file()
    assert (repo / "data" / "events.sqlite3").is_file()


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
    inputs_file = tmp_path / "inputs.example.json"
    assert wf_file.is_file()
    assert inputs_file.is_file()
    content = wf_file.read_text(encoding="utf-8")
    assert "approval_workflow" in content
    assert "request_approval" in content
    assert "Launch notes are ready for review." in inputs_file.read_text(encoding="utf-8")
    assert "template=approval" in result.stdout


def test_init_template_yaml(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--template", "yaml"])
    assert result.exit_code == 0
    wf_file = tmp_path / "workflow.yaml"
    inputs_file = tmp_path / "inputs.example.json"
    assert wf_file.is_file()
    assert inputs_file.is_file()
    content = wf_file.read_text(encoding="utf-8")
    assert "yaml_workflow" in content
    assert json.loads(inputs_file.read_text(encoding="utf-8")) == {}
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


def test_dry_run_with_llm_parse(tmp_path: Path) -> None:
    workflow_path = tmp_path / "dry_parse_flow.py"
    workflow_path.write_text(
        """
from pydantic import BaseModel
from replayt.workflow import Workflow

class Pick(BaseModel):
    label: str

wf = Workflow("dry_parse")
wf.set_initial("ask")

@wf.step("ask")
def ask(ctx):
    out = ctx.llm.parse(Pick, messages=[{"role": "user", "content": "hello"}])
    ctx.set("response", out.label)
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


def test_report_llm_model_filter_note_and_single_output(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    events = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "r1",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "r1",
            "seq": 2,
            "type": "structured_output",
            "payload": {
                "schema_name": "A",
                "data": {"x": 1},
                "effective": {"model": "m-small"},
            },
        },
        {
            "ts": "2026-03-01T00:00:02+00:00",
            "run_id": "r1",
            "seq": 3,
            "type": "structured_output",
            "payload": {
                "schema_name": "B",
                "data": {"x": 2},
                "effective": {"model": "m-large"},
            },
        },
        {
            "ts": "2026-03-01T00:00:03+00:00",
            "run_id": "r1",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / "r1.jsonl").write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")

    runner = CliRunner()
    html = runner.invoke(app, ["report", "r1", "--log-dir", str(log_dir), "--llm-model", "m-large"])
    assert html.exit_code == 0
    assert "LLM model filter:" in html.stdout
    assert "m-large" in html.stdout
    assert "Structured Outputs" in html.stdout
    assert html.stdout.count("m-small") == 0

    md = runner.invoke(
        app, ["report", "r1", "--log-dir", str(log_dir), "--format", "markdown", "--llm-model", "m-large"]
    )
    assert md.exit_code == 0
    assert "**LLM model filter:**" in md.stdout
    assert "`m-large`" in md.stdout
    assert "B" in md.stdout


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
    assert payload["schema"] == "replayt.diff_report.v1"
    assert payload["run_a"] == id_a
    assert payload["run_b"] == id_b
    assert "status" in payload


def test_diff_preserves_multiple_structured_outputs_with_same_schema_name(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "run-a",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "run-a",
            "seq": 2,
            "type": "structured_output",
            "payload": {"state": "first", "schema_name": "Decision", "data": {"label": "A"}},
        },
        {
            "ts": "2026-03-01T00:00:02+00:00",
            "run_id": "run-a",
            "seq": 3,
            "type": "structured_output",
            "payload": {"state": "second", "schema_name": "Decision", "data": {"label": "same"}},
        },
        {
            "ts": "2026-03-01T00:00:03+00:00",
            "run_id": "run-a",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    run_b = [
        {
            "ts": "2026-03-02T00:00:00+00:00",
            "run_id": "run-b",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-02T00:00:01+00:00",
            "run_id": "run-b",
            "seq": 2,
            "type": "structured_output",
            "payload": {"state": "first", "schema_name": "Decision", "data": {"label": "B"}},
        },
        {
            "ts": "2026-03-02T00:00:02+00:00",
            "run_id": "run-b",
            "seq": 3,
            "type": "structured_output",
            "payload": {"state": "second", "schema_name": "Decision", "data": {"label": "same"}},
        },
        {
            "ts": "2026-03-02T00:00:03+00:00",
            "run_id": "run-b",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    (log_dir / "run-a.jsonl").write_text("\n".join(json.dumps(x) for x in run_a) + "\n", encoding="utf-8")
    (log_dir / "run-b.jsonl").write_text("\n".join(json.dumps(x) for x in run_b) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["diff", "run-a", "run-b", "--log-dir", str(log_dir), "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema"] == "replayt.diff_report.v1"
    assert payload["structured_outputs"]["changed"] is True
    assert payload["structured_outputs"]["a_count"] == 2
    assert payload["structured_outputs"]["b_count"] == 2
    assert "1:Decision" in payload["structured_outputs"]["diffs"]


def test_diff_llm_model_filter_slices_outputs_and_latency(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "run-a",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "run-a",
            "seq": 2,
            "type": "state_entered",
            "payload": {"state": "s1"},
        },
        {
            "ts": "2026-03-01T00:00:02+00:00",
            "run_id": "run-a",
            "seq": 3,
            "type": "structured_output",
            "payload": {
                "state": "s1",
                "schema_name": "Out",
                "data": {"v": 1},
                "effective": {"model": "model-a"},
            },
        },
        {
            "ts": "2026-03-01T00:00:03+00:00",
            "run_id": "run-a",
            "seq": 4,
            "type": "llm_response",
            "payload": {"effective": {"model": "model-a"}, "latency_ms": 10},
        },
        {
            "ts": "2026-03-01T00:00:04+00:00",
            "run_id": "run-a",
            "seq": 5,
            "type": "structured_output",
            "payload": {
                "state": "s2",
                "schema_name": "Out",
                "data": {"v": 2},
                "effective": {"model": "model-b"},
            },
        },
        {
            "ts": "2026-03-01T00:00:05+00:00",
            "run_id": "run-a",
            "seq": 6,
            "type": "llm_response",
            "payload": {"effective": {"model": "model-b"}, "latency_ms": 20},
        },
        {
            "ts": "2026-03-01T00:00:06+00:00",
            "run_id": "run-a",
            "seq": 7,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    run_b = [dict(e) for e in run_a]
    for e in run_b:
        e["run_id"] = "run-b"
    (log_dir / "run-a.jsonl").write_text("\n".join(json.dumps(x) for x in run_a) + "\n", encoding="utf-8")
    (log_dir / "run-b.jsonl").write_text("\n".join(json.dumps(x) for x in run_b) + "\n", encoding="utf-8")

    runner = CliRunner()
    r_all = runner.invoke(app, ["diff", "run-a", "run-b", "--log-dir", str(log_dir), "--output", "json"])
    assert r_all.exit_code == 0
    all_payload = json.loads(r_all.stdout)
    assert all_payload["structured_outputs"]["a_count"] == 2
    assert all_payload["latency"]["a_total_ms"] == 30

    r_f = runner.invoke(
        app,
        ["diff", "run-a", "run-b", "--log-dir", str(log_dir), "--output", "json", "--llm-model", "model-a"],
    )
    assert r_f.exit_code == 0
    f_payload = json.loads(r_f.stdout)
    assert f_payload["llm_model_filter"] == ["model-a"]
    assert f_payload["structured_outputs"]["a_count"] == 1
    assert f_payload["structured_outputs"]["changed"] is False
    assert f_payload["latency"]["a_total_ms"] == 10


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


def test_cli_run_missing_module_target_onboarding_hint(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "zzreplayt_cli_missing_mod_12345:wf",
            "--dry-run",
            "--log-dir",
            str(tmp_path),
        ],
    )
    assert r.exit_code != 0
    out = (r.stdout or "") + (r.stderr or "")
    assert "zzreplayt_cli_missing_mod_12345" in out
    assert "pip install" in out.lower()
    assert "PYTHONPATH" in out
    assert "doctor --target" in out.replace("\n", " ")


def test_cli_run_missing_transitive_module_onboarding_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "replayt_onb_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "wf_entry.py").write_text(
        """
from replayt.workflow import Workflow

import definitely_missing_replayt_transitive_mod

wf = Workflow("t")

@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", "replayt_onb_pkg.wf_entry:wf", "--dry-run", "--log-dir", str(tmp_path)],
    )
    assert r.exit_code != 0
    out = (r.stdout or "") + (r.stderr or "")
    assert "definitely_missing_replayt_transitive_mod" in out
    assert "PYTHONPATH" in out


def test_cli_export_hook_failure_aborts_export_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = json.dumps(sys.executable)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nexport_hook = [{exe}, \"-c\", \"import sys; sys.exit(7)\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    tar_path = tmp_path / "out.tar.gz"
    ex = runner.invoke(
        app,
        ["export-run", rid, "--log-dir", str(tmp_path), "--out", str(tar_path)],
    )
    assert ex.exit_code == 1
    assert "export_hook" in (ex.stdout + ex.stderr).lower()
    assert not tar_path.is_file()


def test_cli_export_hook_receives_policy_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook_out = tmp_path / "export_hook.json"
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "Path(os.environ['HOOK_OUT']).write_text("
        "json.dumps({"
        "'run_id': os.environ.get('REPLAYT_RUN_ID'), "
        "'kind': os.environ.get('REPLAYT_EXPORT_KIND'), "
        "'log_dir': os.environ.get('REPLAYT_LOG_DIR'), "
        "'export_mode': os.environ.get('REPLAYT_EXPORT_MODE'), "
        "'out': os.environ.get('REPLAYT_EXPORT_OUT'), "
        "'seal': os.environ.get('REPLAYT_EXPORT_SEAL'), "
        "'count': os.environ.get('REPLAYT_EXPORT_EVENT_COUNT'), "
        "'report_style': os.environ.get('REPLAYT_BUNDLE_REPORT_STYLE'), "
        "'target': os.environ.get('REPLAYT_TARGET'), "
        "'workflow_contract_sha256': os.environ.get('REPLAYT_WORKFLOW_CONTRACT_SHA256'), "
        "'workflow_name': os.environ.get('REPLAYT_WORKFLOW_NAME'), "
        "'workflow_version': os.environ.get('REPLAYT_WORKFLOW_VERSION'), "
        "'metadata': (json.loads(os.environ['REPLAYT_RUN_METADATA_JSON']) "
        "if os.environ.get('REPLAYT_RUN_METADATA_JSON') else None), "
        "'tags': (json.loads(os.environ['REPLAYT_RUN_TAGS_JSON']) "
        "if os.environ.get('REPLAYT_RUN_TAGS_JSON') else None), "
        "'experiment': (json.loads(os.environ['REPLAYT_RUN_EXPERIMENT_JSON']) "
        "if os.environ.get('REPLAYT_RUN_EXPERIMENT_JSON') else None)"
        "}), encoding='utf-8')"
    )
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nexport_hook = [{json.dumps(sys.executable)}, \"-c\", {json.dumps(script)}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOOK_OUT", str(hook_out))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
            '{"deployment_tier":"prod","change_ticket":"CHG-9"}',
            "--tag",
            "team=audit",
            "--experiment-json",
            '{"runbook":"export-gate"}',
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    tar_path = (tmp_path / "bundle.tar.gz").resolve()
    ex = runner.invoke(
        app,
        [
            "export-run",
            rid,
            "--log-dir",
            str(tmp_path),
            "--out",
            str(tar_path),
            "--export-mode",
            "redacted",
            "--seal",
            "--target",
            "replayt_examples.e01_hello_world:wf",
        ],
    )
    assert ex.exit_code == 0
    data = json.loads(hook_out.read_text(encoding="utf-8"))
    assert data["run_id"] == rid
    assert data["kind"] == "export_run"
    assert data["log_dir"] == str(tmp_path.resolve())
    assert data["export_mode"] == "redacted"
    assert data["out"] == str(tar_path)
    assert data["seal"] == "1"
    assert int(data["count"]) > 0
    assert data["report_style"] is None
    assert data["target"] == "replayt_examples.e01_hello_world:wf"
    assert data["workflow_name"] == "hello_world_tutorial"
    assert data["workflow_version"] == "1"
    assert isinstance(data["workflow_contract_sha256"], str) and len(data["workflow_contract_sha256"]) == 64
    assert data["metadata"] == {"change_ticket": "CHG-9", "deployment_tier": "prod"}
    assert data["tags"] == {"team": "audit"}
    assert data["experiment"] == {"runbook": "export-gate"}
    with tarfile.open(tar_path, "r:gz") as tf:
        manifest_member = next(name for name in tf.getnames() if name.endswith("/manifest.json"))
        manifest = json.loads(tf.extractfile(manifest_member).read().decode("utf-8"))
    assert manifest["policy_hook"] == {
        "source": "project_config:export_hook",
        "argv0": Path(sys.executable).name,
        "arg_count": 3,
    }


def test_cli_seal_hook_failure_aborts_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = json.dumps(sys.executable)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nseal_hook = [{exe}, \"-c\", \"import sys; sys.exit(9)\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    seal = runner.invoke(app, ["seal", rid, "--log-dir", str(tmp_path)])
    assert seal.exit_code == 1
    assert "seal_hook" in (seal.stdout + seal.stderr).lower()
    assert not (tmp_path / f"{rid}.seal.json").is_file()


def test_cli_seal_hook_receives_policy_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook_out = tmp_path / "seal_hook.json"
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "Path(os.environ['HOOK_OUT']).write_text("
        "json.dumps({"
        "'run_id': os.environ.get('REPLAYT_RUN_ID'), "
        "'log_dir': os.environ.get('REPLAYT_LOG_DIR'), "
        "'jsonl': os.environ.get('REPLAYT_SEAL_JSONL'), "
        "'out': os.environ.get('REPLAYT_SEAL_OUT'), "
        "'line_count': os.environ.get('REPLAYT_SEAL_LINE_COUNT'), "
        "'workflow_contract_sha256': os.environ.get('REPLAYT_WORKFLOW_CONTRACT_SHA256'), "
        "'workflow_name': os.environ.get('REPLAYT_WORKFLOW_NAME'), "
        "'workflow_version': os.environ.get('REPLAYT_WORKFLOW_VERSION'), "
        "'metadata': (json.loads(os.environ['REPLAYT_RUN_METADATA_JSON']) "
        "if os.environ.get('REPLAYT_RUN_METADATA_JSON') else None), "
        "'tags': (json.loads(os.environ['REPLAYT_RUN_TAGS_JSON']) "
        "if os.environ.get('REPLAYT_RUN_TAGS_JSON') else None), "
        "'experiment': (json.loads(os.environ['REPLAYT_RUN_EXPERIMENT_JSON']) "
        "if os.environ.get('REPLAYT_RUN_EXPERIMENT_JSON') else None)"
        "}), encoding='utf-8')"
    )
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nseal_hook = [{json.dumps(sys.executable)}, \"-c\", {json.dumps(script)}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOOK_OUT", str(hook_out))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

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
            '{"deployment_tier":"prod"}',
            "--tag",
            "seal=required",
            "--experiment-json",
            '{"lane":"compliance"}',
        ],
    )
    assert run.exit_code == 0
    rid = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    jsonl_path = (tmp_path / f"{rid}.jsonl").resolve()
    seal_path = (tmp_path / f"{rid}.seal.json").resolve()
    seal = runner.invoke(app, ["seal", rid, "--log-dir", str(tmp_path)])
    assert seal.exit_code == 0
    data = json.loads(hook_out.read_text(encoding="utf-8"))
    assert data["run_id"] == rid
    assert data["log_dir"] == str(tmp_path.resolve())
    assert data["jsonl"] == str(jsonl_path)
    assert data["out"] == str(seal_path)
    assert int(data["line_count"]) > 0
    assert data["workflow_name"] == "hello_world_tutorial"
    assert data["workflow_version"] == "1"
    assert isinstance(data["workflow_contract_sha256"], str) and len(data["workflow_contract_sha256"]) == 64
    assert data["metadata"] == {"deployment_tier": "prod"}
    assert data["tags"] == {"seal": "required"}
    assert data["experiment"] == {"lane": "compliance"}
    manifest = json.loads(seal_path.read_text(encoding="utf-8"))
    assert manifest["policy_hook"] == {
        "source": "project_config:seal_hook",
        "argv0": Path(sys.executable).name,
        "arg_count": 3,
    }


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
        [
            "export-run",
            rid,
            "--log-dir",
            str(tmp_path),
            "--out",
            str(tar_path),
            "--export-mode",
            "redacted",
            "--target",
            "replayt_examples.e01_hello_world:wf",
            "--seal",
        ],
    )
    assert ex.exit_code == 0
    with tarfile.open(tar_path, "r:gz") as tf:
        names = tf.getnames()
        assert any(n.endswith("events.jsonl") for n in names)
        assert any(n.endswith("workflow.contract.json") for n in names)
        assert any(n.endswith("events.seal.json") for n in names)
        member = [n for n in names if n.endswith("events.jsonl")][0]
        data = tf.extractfile(member).read().decode()
        manifest_member = [n for n in names if n.endswith("manifest.json")][0]
        manifest = json.loads(tf.extractfile(manifest_member).read().decode("utf-8"))
        seal_member = [n for n in names if n.endswith("events.seal.json")][0]
        seal_data = json.loads(tf.extractfile(seal_member).read().decode("utf-8"))
        contract_member = [n for n in names if n.endswith("workflow.contract.json")][0]
        contract_data = json.loads(tf.extractfile(contract_member).read().decode("utf-8"))
    first = json.loads(data.splitlines()[0])
    assert first["type"] == "run_started"
    assert first["payload"].get("inputs") == {}
    assert first["payload"].get("run_metadata") == {"experiment": "a"}
    assert manifest["run_summary"]["workflow_name"] == "hello_world_tutorial"
    assert manifest["run_summary"]["status"] == "completed"
    assert manifest["run_summary"]["run_metadata"] == {"experiment": "a"}
    assert manifest["workflow_contract_snapshot"] == {
        "target": "replayt_examples.e01_hello_world:wf",
        "file": "workflow.contract.json",
        "contract_sha256": contract_data["contract_sha256"],
        "matches_run_started": True,
    }
    assert seal_data["schema"] == "replayt.export_seal.v1"
    assert seal_data["run_id"] == rid
    assert seal_data["jsonl_path"] == "events.jsonl"


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


def test_cli_runs_filter_status(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    completed = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "rid-ok",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "rid-ok",
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    failed = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "rid-bad",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "rid-bad",
            "seq": 2,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    paused = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "rid-wait",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "rid-wait",
            "seq": 2,
            "type": "run_paused",
            "payload": {"reason": "approval_required", "approval_id": "a1"},
        },
    ]
    unknown_only = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "rid-open",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
    ]
    for lines, name in (
        (completed, "rid-ok"),
        (failed, "rid-bad"),
        (paused, "rid-wait"),
        (unknown_only, "rid-open"),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    r_paused = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--status", "paused"])
    assert r_paused.exit_code == 0
    assert "rid-wait" in r_paused.stdout
    assert "rid-ok" not in r_paused.stdout
    assert "rid-bad" not in r_paused.stdout

    r_or = runner.invoke(
        app, ["runs", "--log-dir", str(log_dir), "--status", "failed", "--status", "unknown"]
    )
    assert r_or.exit_code == 0
    out_or = r_or.stdout
    assert "rid-bad" in out_or and "rid-open" in out_or
    assert "rid-ok" not in out_or
    assert "rid-wait" not in out_or

    bad = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--status", "nope"])
    assert bad.exit_code != 0
    assert "Invalid --status" in (bad.stdout + (bad.stderr or ""))


def test_cli_runs_text_surfaces_pending_approval_attention(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    paused = [
        {
            "ts": "2026-03-22T10:00:00+00:00",
            "run_id": "rid-wait",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "publish", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-22T10:00:01+00:00",
            "run_id": "rid-wait",
            "seq": 2,
            "type": "approval_requested",
            "payload": {"approval_id": "ship", "state": "review", "summary": "Ship draft?"},
        },
        {
            "ts": "2026-03-22T10:00:02+00:00",
            "run_id": "rid-wait",
            "seq": 3,
            "type": "run_paused",
            "payload": {"reason": "approval_required", "approval_id": "ship"},
        },
    ]
    (log_dir / "rid-wait.jsonl").write_text("\n".join(json.dumps(x) for x in paused) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--status", "paused"])
    assert result.exit_code == 0
    assert "attention=awaiting approval ship @ review" in result.stdout


def test_cli_runs_output_json_reports_filters_and_age(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import replayt.cli.commands.inspect as inspect_cmd

    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            base = cls.fromisoformat("2026-03-22T12:00:00+00:00")
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(inspect_cmd, "datetime", FrozenDateTime)

    stale = [
        {
            "ts": "2026-03-22T09:00:00+00:00",
            "run_id": "rid-stale",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-22T09:30:00+00:00",
            "run_id": "rid-stale",
            "seq": 2,
            "type": "run_paused",
            "payload": {"approval_id": "ship"},
        },
    ]
    fresh = [
        {
            "ts": "2026-03-22T11:40:00+00:00",
            "run_id": "rid-fresh",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-22T11:50:00+00:00",
            "run_id": "rid-fresh",
            "seq": 2,
            "type": "run_paused",
            "payload": {"approval_id": "ship"},
        },
    ]
    for lines, name in ((stale, "rid-stale"), (fresh, "rid-fresh")):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "runs",
            "--log-dir",
            str(log_dir),
            "--status",
            "paused",
            "--older-than",
            "1h",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema"] == "replayt.runs_report.v1"
    assert data["count"] == 1
    assert data["filters"]["status"] == ["paused"]
    assert data["filters"]["older_than"] == "1h"
    assert data["filters"]["newer_than"] is None
    assert data["runs"][0]["run_id"] == "rid-stale"
    assert data["runs"][0]["status"] == "paused"
    assert data["runs"][0]["attention_kind"] == "pending_approval"
    assert data["runs"][0]["attention_summary"] == "awaiting approval ship"
    assert data["runs"][0]["pending_approvals"][0]["approval_id"] == "ship"
    assert data["runs"][0]["last_event_age_seconds"] == 9000


def test_cli_runs_output_json_includes_failure_attention_and_parse_context(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    failed = [
        {
            "ts": "2026-03-22T09:00:00+00:00",
            "run_id": "rid-bad",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "support_flow", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-22T09:00:01+00:00",
            "run_id": "rid-bad",
            "seq": 2,
            "type": "structured_output_failed",
            "payload": {
                "state": "triage",
                "schema_name": "Decision",
                "stage": "schema_validate",
                "error": {"message": "confidence must be <= 1"},
            },
        },
        {
            "ts": "2026-03-22T09:00:02+00:00",
            "run_id": "rid-bad",
            "seq": 3,
            "type": "run_failed",
            "payload": {
                "state": "triage",
                "error": {"type": "ValueError", "message": "confidence must be <= 1"},
            },
        },
        {
            "ts": "2026-03-22T09:00:03+00:00",
            "run_id": "rid-bad",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    (log_dir / "rid-bad.jsonl").write_text("\n".join(json.dumps(x) for x in failed) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    run = data["runs"][0]
    assert run["run_id"] == "rid-bad"
    assert run["attention_kind"] == "run_failed"
    assert run["attention_summary"] == "failed in triage: ValueError: confidence must be <= 1"
    assert run["latest_failure"]["state"] == "triage"
    assert run["latest_structured_output_failure"]["schema_name"] == "Decision"
    assert run["latest_structured_output_failure"]["stage"] == "schema_validate"


def test_cli_runs_newer_than_filters_recent_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import replayt.cli.commands.inspect as inspect_cmd

    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            base = cls.fromisoformat("2026-03-22T12:00:00+00:00")
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(inspect_cmd, "datetime", FrozenDateTime)

    for rid, ts in (("rid-old", "2026-03-22T10:00:00+00:00"), ("rid-new", "2026-03-22T11:50:00+00:00")):
        lines = [
            {
                "ts": ts,
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            },
            {
                "ts": ts,
                "run_id": rid,
                "seq": 2,
                "type": "run_completed",
                "payload": {"status": "completed"},
            },
        ]
        (log_dir / f"{rid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--newer-than", "30m"])
    assert result.exit_code == 0
    assert "rid-new" in result.stdout
    assert "rid-old" not in result.stdout


def test_cli_runs_tool_filter(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    def _run_with_tools(tool_names: list[str], rid: str) -> list[dict]:
        lines = [
            {
                "ts": "2026-03-01T00:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            },
        ]
        seq = 2
        for name in tool_names:
            lines.append(
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": rid,
                    "seq": seq,
                    "type": "tool_call",
                    "payload": {"state": "s", "name": name, "arguments": {}},
                }
            )
            seq += 1
        lines.append(
            {
                "ts": "2026-03-01T00:00:02+00:00",
                "run_id": rid,
                "seq": seq,
                "type": "run_completed",
                "payload": {"status": "completed"},
            }
        )
        return lines

    for lines, name in (
        (_run_with_tools(["lookup"], "rid-a"), "rid-a"),
        (_run_with_tools(["other"], "rid-b"), "rid-b"),
        (
            [
                {
                    "ts": "2026-03-01T00:00:00+00:00",
                    "run_id": "rid-c",
                    "seq": 1,
                    "type": "run_started",
                    "payload": {"workflow_name": "w", "workflow_version": "1"},
                },
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": "rid-c",
                    "seq": 2,
                    "type": "run_completed",
                    "payload": {"status": "completed"},
                },
            ],
            "rid-c",
        ),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    r_one = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--tool", "lookup"])
    assert r_one.exit_code == 0
    assert "rid-a" in r_one.stdout
    assert "rid-b" not in r_one.stdout
    assert "rid-c" not in r_one.stdout

    r_or = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--tool", "lookup", "--tool", "other"])
    assert r_or.exit_code == 0
    assert "rid-a" in r_or.stdout and "rid-b" in r_or.stdout
    assert "rid-c" not in r_or.stdout

    bad = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--tool", ""])
    assert bad.exit_code != 0
    assert "Empty --tool" in (bad.stdout + (bad.stderr or ""))

    r_stats = runner.invoke(
        app,
        ["stats", "--log-dir", str(log_dir), "--tool", "lookup", "--output", "json"],
    )
    assert r_stats.exit_code == 0
    stats_payload = json.loads(r_stats.stdout)
    assert stats_payload["schema"] == "replayt.stats_report.v1"
    assert stats_payload["runs_included"] == 1

    inspect_one = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--output", "json", "--tool", "lookup"],
    )
    assert inspect_one.exit_code == 0
    inspect_payload = json.loads(inspect_one.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["tool_name_filter"] == ["lookup"]
    assert [e["type"] for e in inspect_payload["events"]] == ["tool_call"]

    inspect_or = runner.invoke(
        app,
        [
            "inspect",
            "rid-a",
            "--log-dir",
            str(log_dir),
            "--output",
            "json",
            "--tool",
            "lookup",
            "--tool",
            "missing",
        ],
    )
    assert inspect_or.exit_code == 0
    inspect_or_payload = json.loads(inspect_or.stdout)
    assert inspect_or_payload["tool_name_filter"] == ["lookup", "missing"]
    assert [e["type"] for e in inspect_or_payload["events"]] == ["tool_call"]

    bad_inspect = runner.invoke(app, ["inspect", "rid-a", "--log-dir", str(log_dir), "--tool", ""])
    assert bad_inspect.exit_code != 0
    assert "Empty --tool" in (bad_inspect.stdout + (bad_inspect.stderr or ""))


def test_cli_runs_and_stats_filter_by_note_kind(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    def _run_with_notes(note_kinds: list[str], rid: str) -> list[dict[str, object]]:
        lines: list[dict[str, object]] = [
            {
                "ts": "2026-03-01T00:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            }
        ]
        seq = 2
        for kind in note_kinds:
            lines.append(
                {
                    "ts": f"2026-03-01T00:00:0{seq-1}+00:00",
                    "run_id": rid,
                    "seq": seq,
                    "type": "step_note",
                    "payload": {"state": "compose", "kind": kind, "summary": f"{kind} done"},
                }
            )
            seq += 1
        lines.append(
            {
                "ts": "2026-03-01T00:00:09+00:00",
                "run_id": rid,
                "seq": seq,
                "type": "run_completed",
                "payload": {"status": "completed"},
            }
        )
        return lines

    for lines, name in (
        (_run_with_notes(["framework_summary"], "rid-a"), "rid-a"),
        (_run_with_notes(["subrun_link"], "rid-b"), "rid-b"),
        (
            [
                {
                    "ts": "2026-03-01T00:00:00+00:00",
                    "run_id": "rid-c",
                    "seq": 1,
                    "type": "run_started",
                    "payload": {"workflow_name": "w", "workflow_version": "1"},
                },
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": "rid-c",
                    "seq": 2,
                    "type": "run_completed",
                    "payload": {"status": "completed"},
                },
            ],
            "rid-c",
        ),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    inspect = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--output", "json", "--note-kind", "framework_summary"],
    )
    assert inspect.exit_code == 0
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["note_kind_filter"] == ["framework_summary"]
    assert [e["type"] for e in inspect_payload["events"]] == ["step_note"]

    r_one = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--note-kind", "framework_summary"])
    assert r_one.exit_code == 0
    assert "rid-a" in r_one.stdout
    assert "rid-b" not in r_one.stdout
    assert "rid-c" not in r_one.stdout

    r_or = runner.invoke(
        app,
        ["runs", "--log-dir", str(log_dir), "--note-kind", "framework_summary", "--note-kind", "subrun_link"],
    )
    assert r_or.exit_code == 0
    assert "rid-a" in r_or.stdout and "rid-b" in r_or.stdout
    assert "rid-c" not in r_or.stdout

    bad = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--note-kind", ""])
    assert bad.exit_code != 0
    assert "Empty --note-kind" in (bad.stdout + (bad.stderr or ""))

    r_stats = runner.invoke(
        app,
        ["stats", "--log-dir", str(log_dir), "--note-kind", "framework_summary", "--output", "json"],
    )
    assert r_stats.exit_code == 0
    stats_payload = json.loads(r_stats.stdout)
    assert stats_payload["schema"] == "replayt.stats_report.v1"
    assert stats_payload["runs_included"] == 1


def test_cli_runs_and_stats_filter_by_finish_reason(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    def _run_with_finish_reasons(reasons: list[str], rid: str) -> list[dict[str, object]]:
        lines: list[dict[str, object]] = [
            {
                "ts": "2026-03-01T00:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            }
        ]
        seq = 2
        for fr in reasons:
            lines.append(
                {
                    "ts": f"2026-03-01T00:00:{seq - 1:02d}+00:00",
                    "run_id": rid,
                    "seq": seq,
                    "type": "llm_response",
                    "payload": {"finish_reason": fr, "latency_ms": 10},
                }
            )
            seq += 1
        lines.append(
            {
                "ts": "2026-03-01T00:00:09+00:00",
                "run_id": rid,
                "seq": seq,
                "type": "run_completed",
                "payload": {"status": "completed"},
            }
        )
        return lines

    for lines, name in (
        (_run_with_finish_reasons(["length"], "rid-a"), "rid-a"),
        (_run_with_finish_reasons(["stop"], "rid-b"), "rid-b"),
        (
            [
                {
                    "ts": "2026-03-01T00:00:00+00:00",
                    "run_id": "rid-c",
                    "seq": 1,
                    "type": "run_started",
                    "payload": {"workflow_name": "w", "workflow_version": "1"},
                },
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": "rid-c",
                    "seq": 2,
                    "type": "run_completed",
                    "payload": {"status": "completed"},
                },
            ],
            "rid-c",
        ),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    inspect = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--output", "json", "--finish-reason", "length"],
    )
    assert inspect.exit_code == 0
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["finish_reason_filter"] == ["length"]
    assert [e["type"] for e in inspect_payload["events"]] == ["llm_response"]

    r_one = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--finish-reason", "length", "--output", "json"])
    assert r_one.exit_code == 0
    runs_payload = json.loads(r_one.stdout)
    assert runs_payload["schema"] == "replayt.runs_report.v1"
    assert runs_payload["filters"]["finish_reason"] == ["length"]
    assert len(runs_payload["runs"]) == 1
    assert runs_payload["runs"][0]["run_id"] == "rid-a"

    r_text = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--finish-reason", "length"])
    assert r_text.exit_code == 0
    assert "rid-a" in r_text.stdout
    assert "rid-b" not in r_text.stdout
    assert "rid-c" not in r_text.stdout

    r_or = runner.invoke(
        app,
        ["runs", "--log-dir", str(log_dir), "--finish-reason", "length", "--finish-reason", "stop"],
    )
    assert r_or.exit_code == 0
    assert "rid-a" in r_or.stdout and "rid-b" in r_or.stdout
    assert "rid-c" not in r_or.stdout

    bad = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--finish-reason", ""])
    assert bad.exit_code != 0
    assert "Empty --finish-reason" in (bad.stdout + (bad.stderr or ""))

    r_stats = runner.invoke(
        app,
        ["stats", "--log-dir", str(log_dir), "--finish-reason", "length", "--output", "json"],
    )
    assert r_stats.exit_code == 0
    stats_payload = json.loads(r_stats.stdout)
    assert stats_payload["schema"] == "replayt.stats_report.v1"
    assert stats_payload["runs_included"] == 1


def test_cli_runs_structured_schema_filter(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    def _run_with_struct(
        schema_names: list[str],
        rid: str,
        *,
        failed: bool = False,
    ) -> list[dict]:
        lines = [
            {
                "ts": "2026-03-01T00:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            },
        ]
        seq = 2
        typ = "structured_output_failed" if failed else "structured_output"
        for sn in schema_names:
            lines.append(
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": rid,
                    "seq": seq,
                    "type": typ,
                    "payload": {"state": "s", "schema_name": sn, "data": {}},
                }
            )
            seq += 1
        lines.append(
            {
                "ts": "2026-03-01T00:00:02+00:00",
                "run_id": rid,
                "seq": seq,
                "type": "run_completed",
                "payload": {"status": "completed"},
            }
        )
        return lines

    for lines, name in (
        (_run_with_struct(["Decision"], "rid-a"), "rid-a"),
        (_run_with_struct(["OtherSchema"], "rid-b"), "rid-b"),
        (_run_with_struct(["Decision"], "rid-fail", failed=True), "rid-fail"),
        (
            [
                {
                    "ts": "2026-03-01T00:00:00+00:00",
                    "run_id": "rid-c",
                    "seq": 1,
                    "type": "run_started",
                    "payload": {"workflow_name": "w", "workflow_version": "1"},
                },
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": "rid-c",
                    "seq": 2,
                    "type": "run_completed",
                    "payload": {"status": "completed"},
                },
            ],
            "rid-c",
        ),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    inspect_one = runner.invoke(
        app,
        [
            "inspect",
            "rid-a",
            "--log-dir",
            str(log_dir),
            "--output",
            "json",
            "--structured-schema",
            "Decision",
        ],
    )
    assert inspect_one.exit_code == 0
    inspect_payload = json.loads(inspect_one.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["structured_schema_filter"] == ["Decision"]
    assert [e["type"] for e in inspect_payload["events"]] == ["structured_output"]

    inspect_or = runner.invoke(
        app,
        [
            "inspect",
            "rid-b",
            "--log-dir",
            str(log_dir),
            "--output",
            "json",
            "--structured-schema",
            "Decision",
            "--structured-schema",
            "OtherSchema",
        ],
    )
    assert inspect_or.exit_code == 0
    or_inspect = json.loads(inspect_or.stdout)
    assert sorted(or_inspect["structured_schema_filter"]) == ["Decision", "OtherSchema"]
    assert [e["type"] for e in or_inspect["events"]] == ["structured_output"]

    bad_inspect = runner.invoke(
        app, ["inspect", "rid-a", "--log-dir", str(log_dir), "--structured-schema", ""]
    )
    assert bad_inspect.exit_code != 0
    assert "Empty --structured-schema" in (bad_inspect.stdout + (bad_inspect.stderr or ""))

    md_bad = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--output", "markdown", "--structured-schema", "Decision"],
    )
    assert md_bad.exit_code != 0
    assert "--structured-schema" in (md_bad.stdout + (md_bad.stderr or ""))

    r_one = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--structured-schema", "Decision"])
    assert r_one.exit_code == 0
    assert "rid-a" in r_one.stdout
    assert "rid-fail" in r_one.stdout
    assert "rid-b" not in r_one.stdout
    assert "rid-c" not in r_one.stdout

    r_or = runner.invoke(
        app,
        ["runs", "--log-dir", str(log_dir), "--structured-schema", "Decision", "--structured-schema", "OtherSchema"],
    )
    assert r_or.exit_code == 0
    assert "rid-a" in r_or.stdout and "rid-b" in r_or.stdout
    assert "rid-c" not in r_or.stdout

    bad = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--structured-schema", ""])
    assert bad.exit_code != 0
    assert "Empty --structured-schema" in (bad.stdout + (bad.stderr or ""))

    r_stats = runner.invoke(
        app,
        ["stats", "--log-dir", str(log_dir), "--structured-schema", "Decision", "--output", "json"],
    )
    assert r_stats.exit_code == 0
    stats_payload = json.loads(r_stats.stdout)
    assert stats_payload["runs_included"] == 2

    # AND between --tool and --structured-schema
    (log_dir / "rid-both.jsonl").write_text(
        "\n".join(
            json.dumps(x)
            for x in [
                {
                    "ts": "2026-03-01T00:00:00+00:00",
                    "run_id": "rid-both",
                    "seq": 1,
                    "type": "run_started",
                    "payload": {"workflow_name": "w", "workflow_version": "1"},
                },
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": "rid-both",
                    "seq": 2,
                    "type": "structured_output",
                    "payload": {"state": "s", "schema_name": "Decision", "data": {}},
                },
                {
                    "ts": "2026-03-01T00:00:02+00:00",
                    "run_id": "rid-both",
                    "seq": 3,
                    "type": "tool_call",
                    "payload": {"state": "s", "name": "lookup", "arguments": {}},
                },
                {
                    "ts": "2026-03-01T00:00:03+00:00",
                    "run_id": "rid-both",
                    "seq": 4,
                    "type": "run_completed",
                    "payload": {"status": "completed"},
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    r_and = runner.invoke(
        app,
        [
            "runs",
            "--log-dir",
            str(log_dir),
            "--structured-schema",
            "Decision",
            "--tool",
            "lookup",
        ],
    )
    assert r_and.exit_code == 0
    assert "rid-both" in r_and.stdout
    assert "rid-a" not in r_and.stdout


def test_cli_runs_llm_model_filter(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    def _run_with_models(models: list[str | None], rid: str, *, legacy: bool = False) -> list[dict]:
        lines = [
            {
                "ts": "2026-03-01T00:00:00+00:00",
                "run_id": rid,
                "seq": 1,
                "type": "run_started",
                "payload": {"workflow_name": "w", "workflow_version": "1"},
            },
        ]
        seq = 2
        for m in models:
            if legacy and m is not None:
                payload: dict = {"finish_reason": "stop", "latency_ms": 1, "model": m}
            elif m is not None:
                payload = {"finish_reason": "stop", "latency_ms": 1, "effective": {"model": m}}
            else:
                payload = {"finish_reason": "stop", "latency_ms": 1}
            lines.append(
                {
                    "ts": "2026-03-01T00:00:01+00:00",
                    "run_id": rid,
                    "seq": seq,
                    "type": "llm_response",
                    "payload": payload,
                }
            )
            seq += 1
        lines.append(
            {
                "ts": "2026-03-01T00:00:02+00:00",
                "run_id": rid,
                "seq": seq,
                "type": "run_completed",
                "payload": {"status": "completed"},
            }
        )
        return lines

    for lines, name in (
        (_run_with_models(["gpt-4o-mini"], "rid-a"), "rid-a"),
        (_run_with_models(["claude-opus"], "rid-b"), "rid-b"),
        (_run_with_models(["gpt-4o-mini"], "rid-legacy", legacy=True), "rid-legacy"),
        (_run_with_models([], "rid-c"), "rid-c"),
    ):
        (log_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )

    runner = CliRunner()
    inspect_one = runner.invoke(
        app,
        [
            "inspect",
            "rid-a",
            "--log-dir",
            str(log_dir),
            "--output",
            "json",
            "--llm-model",
            "gpt-4o-mini",
        ],
    )
    assert inspect_one.exit_code == 0
    inspect_payload = json.loads(inspect_one.stdout)
    assert inspect_payload["schema"] == "replayt.inspect_report.v1"
    assert inspect_payload["llm_model_filter"] == ["gpt-4o-mini"]
    assert [e["type"] for e in inspect_payload["events"]] == ["llm_response"]

    inspect_or = runner.invoke(
        app,
        [
            "inspect",
            "rid-b",
            "--log-dir",
            str(log_dir),
            "--output",
            "json",
            "--llm-model",
            "gpt-4o-mini",
            "--llm-model",
            "claude-opus",
        ],
    )
    assert inspect_or.exit_code == 0
    or_inspect = json.loads(inspect_or.stdout)
    assert sorted(or_inspect["llm_model_filter"]) == ["claude-opus", "gpt-4o-mini"]
    assert [e["type"] for e in or_inspect["events"]] == ["llm_response"]

    bad_inspect = runner.invoke(app, ["inspect", "rid-a", "--log-dir", str(log_dir), "--llm-model", ""])
    assert bad_inspect.exit_code != 0
    assert "Empty --llm-model" in (bad_inspect.stdout + (bad_inspect.stderr or ""))

    md_bad = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--output", "markdown", "--llm-model", "gpt-4o-mini"],
    )
    assert md_bad.exit_code != 0
    assert "--llm-model" in (md_bad.stdout + (md_bad.stderr or ""))

    inputs_bad = runner.invoke(
        app,
        ["inspect", "rid-a", "--log-dir", str(log_dir), "--print-inputs", "--llm-model", "gpt-4o-mini"],
    )
    assert inputs_bad.exit_code != 0
    assert "--llm-model" in (inputs_bad.stdout + (inputs_bad.stderr or ""))

    r_one = runner.invoke(app, ["runs", "--log-dir", str(log_dir), "--llm-model", "gpt-4o-mini"])
    assert r_one.exit_code == 0
    assert "rid-a" in r_one.stdout
    assert "rid-legacy" in r_one.stdout
    assert "rid-b" not in r_one.stdout
    assert "rid-c" not in r_one.stdout

    r_json = runner.invoke(
        app, ["runs", "--log-dir", str(log_dir), "--llm-model", "gpt-4o-mini", "--output", "json"]
    )
    assert r_json.exit_code == 0
    runs_payload = json.loads(r_json.stdout)
    assert runs_payload["filters"]["llm_model"] == ["gpt-4o-mini"]

    r_stats = runner.invoke(
        app, ["stats", "--log-dir", str(log_dir), "--llm-model", "gpt-4o-mini", "--output", "json"]
    )
    assert r_stats.exit_code == 0
    stats_payload = json.loads(r_stats.stdout)
    assert stats_payload["runs_included"] == 2


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


def test_cli_report_diff_markdown(tmp_path: Path) -> None:
    wf = tmp_path / "rdmd.py"
    wf.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("rdmd")
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
    out = tmp_path / "diff.md"
    r = runner.invoke(
        app,
        [
            "report-diff",
            id_a,
            id_b,
            "--log-dir",
            str(tmp_path),
            "--format",
            "markdown",
            "--out",
            str(out),
        ],
    )
    assert r.exit_code == 0
    md = out.read_text(encoding="utf-8")
    assert "# Run comparison" in md
    assert f"`{id_a}`" in md and f"`{id_b}`" in md
    assert "## Run context" in md
    assert "Generated by replayt" in md


def test_cli_report_diff_preserves_repeated_outputs_and_approvals(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-01T00:00:00+00:00",
            "run_id": "dup-a",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-01T00:00:01+00:00",
            "run_id": "dup-a",
            "seq": 2,
            "type": "approval_requested",
            "payload": {"approval_id": "ship", "state": "gate-1", "summary": "First approval"},
        },
        {
            "ts": "2026-03-01T00:00:02+00:00",
            "run_id": "dup-a",
            "seq": 3,
            "type": "approval_resolved",
            "payload": {"approval_id": "ship", "approved": True},
        },
        {
            "ts": "2026-03-01T00:00:03+00:00",
            "run_id": "dup-a",
            "seq": 4,
            "type": "approval_requested",
            "payload": {"approval_id": "ship", "state": "gate-2", "summary": "Second approval"},
        },
        {
            "ts": "2026-03-01T00:00:04+00:00",
            "run_id": "dup-a",
            "seq": 5,
            "type": "approval_resolved",
            "payload": {"approval_id": "ship", "approved": False},
        },
        {
            "ts": "2026-03-01T00:00:05+00:00",
            "run_id": "dup-a",
            "seq": 6,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "data": {"value": "alpha"}},
        },
        {
            "ts": "2026-03-01T00:00:06+00:00",
            "run_id": "dup-a",
            "seq": 7,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "data": {"value": "stable"}},
        },
        {
            "ts": "2026-03-01T00:00:07+00:00",
            "run_id": "dup-a",
            "seq": 8,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    run_b = [
        {
            "ts": "2026-03-02T00:00:00+00:00",
            "run_id": "dup-b",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "w", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-02T00:00:01+00:00",
            "run_id": "dup-b",
            "seq": 2,
            "type": "approval_requested",
            "payload": {"approval_id": "ship", "state": "gate-1", "summary": "First approval"},
        },
        {
            "ts": "2026-03-02T00:00:02+00:00",
            "run_id": "dup-b",
            "seq": 3,
            "type": "approval_resolved",
            "payload": {"approval_id": "ship", "approved": False},
        },
        {
            "ts": "2026-03-02T00:00:03+00:00",
            "run_id": "dup-b",
            "seq": 4,
            "type": "approval_requested",
            "payload": {"approval_id": "ship", "state": "gate-2", "summary": "Second approval"},
        },
        {
            "ts": "2026-03-02T00:00:04+00:00",
            "run_id": "dup-b",
            "seq": 5,
            "type": "approval_resolved",
            "payload": {"approval_id": "ship", "approved": False},
        },
        {
            "ts": "2026-03-02T00:00:05+00:00",
            "run_id": "dup-b",
            "seq": 6,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "data": {"value": "beta"}},
        },
        {
            "ts": "2026-03-02T00:00:06+00:00",
            "run_id": "dup-b",
            "seq": 7,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "data": {"value": "stable"}},
        },
        {
            "ts": "2026-03-02T00:00:07+00:00",
            "run_id": "dup-b",
            "seq": 8,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    for rid, events in (("dup-a", run_a), ("dup-b", run_b)):
        (log_dir / f"{rid}.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    runner = CliRunner()
    report = runner.invoke(app, ["report", "dup-a", "--log-dir", str(log_dir)])
    assert report.exit_code == 0
    assert "First approval" in report.stdout
    assert "Second approval" in report.stdout
    assert report.stdout.count("Approval ID:</span> <code class=\"rp-code\">ship</code>") == 2

    diff = runner.invoke(app, ["report-diff", "dup-a", "dup-b", "--log-dir", str(log_dir)])
    assert diff.exit_code == 0
    assert "Decision #1" in diff.stdout
    assert "Decision #2" in diff.stdout
    assert "ship #1" in diff.stdout
    assert "ship #2" in diff.stdout
    assert diff.stdout.count("different") >= 2


def test_cli_report_diff_markdown_preserves_repeated_outputs_and_approvals(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-21T10:00:00+00:00",
            "run_id": "dup-a",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "dup", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-21T10:00:01+00:00",
            "run_id": "dup-a",
            "seq": 2,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "state": "classify", "data": {"result": "accept"}},
        },
        {
            "ts": "2026-03-21T10:00:02+00:00",
            "run_id": "dup-a",
            "seq": 3,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "state": "review", "data": {"result": "ship"}},
        },
        {
            "ts": "2026-03-21T10:00:03+00:00",
            "run_id": "dup-a",
            "seq": 4,
            "type": "approval_requested",
            "payload": {"state": "review", "approval_id": "ship", "summary": "First approval"},
        },
        {
            "ts": "2026-03-21T10:00:04+00:00",
            "run_id": "dup-a",
            "seq": 5,
            "type": "approval_requested",
            "payload": {"state": "review", "approval_id": "ship", "summary": "Second approval"},
        },
        {
            "ts": "2026-03-21T10:00:05+00:00",
            "run_id": "dup-a",
            "seq": 6,
            "type": "run_completed",
            "payload": {"status": "paused"},
        },
    ]
    run_b = [
        {
            "ts": "2026-03-21T10:05:00+00:00",
            "run_id": "dup-b",
            "seq": 1,
            "type": "run_started",
            "payload": {"workflow_name": "dup", "workflow_version": "1"},
        },
        {
            "ts": "2026-03-21T10:05:01+00:00",
            "run_id": "dup-b",
            "seq": 2,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "state": "classify", "data": {"result": "accept"}},
        },
        {
            "ts": "2026-03-21T10:05:02+00:00",
            "run_id": "dup-b",
            "seq": 3,
            "type": "structured_output",
            "payload": {"schema_name": "Decision", "state": "review", "data": {"result": "hold"}},
        },
        {
            "ts": "2026-03-21T10:05:03+00:00",
            "run_id": "dup-b",
            "seq": 4,
            "type": "approval_requested",
            "payload": {"state": "review", "approval_id": "ship", "summary": "First approval"},
        },
        {
            "ts": "2026-03-21T10:05:04+00:00",
            "run_id": "dup-b",
            "seq": 5,
            "type": "approval_requested",
            "payload": {"state": "review", "approval_id": "ship", "summary": "Second approval changed"},
        },
        {
            "ts": "2026-03-21T10:05:05+00:00",
            "run_id": "dup-b",
            "seq": 6,
            "type": "run_completed",
            "payload": {"status": "paused"},
        },
    ]
    for rid, events in (("dup-a", run_a), ("dup-b", run_b)):
        (log_dir / f"{rid}.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    runner = CliRunner()
    diff = runner.invoke(app, ["report-diff", "dup-a", "dup-b", "--log-dir", str(log_dir), "--format", "markdown"])

    assert diff.exit_code == 0
    assert "# Run comparison" in diff.stdout
    assert "### Decision #1" in diff.stdout
    assert "### Decision #2" in diff.stdout
    assert "### ship #1" in diff.stdout
    assert "### ship #2" in diff.stdout
    assert diff.stdout.count("- Match: no") >= 2


def test_cli_report_diff_includes_context_and_failure_sections(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-21T12:00:00+00:00",
            "run_id": "ctx-a",
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "ctx",
                "workflow_version": "1",
                "run_metadata": {"tenant": "acme"},
                "experiment": {"lane": "a"},
                "workflow_meta": {"surface": "support"},
            },
        },
        {
            "ts": "2026-03-21T12:00:01+00:00",
            "run_id": "ctx-a",
            "seq": 2,
            "type": "run_failed",
            "payload": {"state": "classify", "error": {"type": "RuntimeError", "message": "bad input"}},
        },
        {
            "ts": "2026-03-21T12:00:02+00:00",
            "run_id": "ctx-a",
            "seq": 3,
            "type": "structured_output_failed",
            "payload": {
                "state": "classify",
                "schema_name": "Decision",
                "stage": "json_decode",
                "structured_output_mode": "prompt_only",
                "error": {"type": "JSONDecodeError", "message": "bad json"},
            },
        },
        {
            "ts": "2026-03-21T12:00:03+00:00",
            "run_id": "ctx-a",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    run_b = [
        {
            "ts": "2026-03-21T12:10:00+00:00",
            "run_id": "ctx-b",
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "ctx",
                "workflow_version": "1",
                "run_metadata": {"tenant": "globex"},
                "experiment": {"lane": "b"},
                "workflow_meta": {"surface": "product"},
            },
        },
        {
            "ts": "2026-03-21T12:10:01+00:00",
            "run_id": "ctx-b",
            "seq": 2,
            "type": "retry_scheduled",
            "payload": {
                "state": "classify",
                "attempt": 1,
                "max_attempts": 2,
                "error": {"type": "TimeoutError", "message": "slow upstream"},
            },
        },
        {
            "ts": "2026-03-21T12:10:02+00:00",
            "run_id": "ctx-b",
            "seq": 3,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    for rid, events in (("ctx-a", run_a), ("ctx-b", run_b)):
        (log_dir / f"{rid}.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    runner = CliRunner()
    diff = runner.invoke(app, ["report-diff", "ctx-a", "ctx-b", "--log-dir", str(log_dir)])

    assert diff.exit_code == 0
    assert "Run context" in diff.stdout
    assert "Failure and pause signals" in diff.stdout
    assert "Experiment" in diff.stdout
    assert "Workflow metadata" in diff.stdout
    assert "Run failure" in diff.stdout
    assert "Latest structured parse failure" in diff.stdout
    assert "attention=" in diff.stdout

    sup = runner.invoke(
        app,
        ["report-diff", "ctx-a", "ctx-b", "--log-dir", str(log_dir), "--style", "support"],
    )
    assert sup.exit_code == 0
    assert sup.stdout.index("Failure and pause signals") < sup.stdout.index("Run context")
    assert diff.stdout.index("Run context") < diff.stdout.index("Failure and pause signals")

    st = runner.invoke(
        app,
        ["report-diff", "ctx-a", "ctx-b", "--log-dir", str(log_dir), "--style", "stakeholder"],
    )
    assert st.exit_code == 0
    assert "Run summary (comparison)" in st.stdout


def test_cli_report_diff_markdown_writes_context_and_failure_sections(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    run_a = [
        {
            "ts": "2026-03-21T12:00:00+00:00",
            "run_id": "ctx-a",
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "ctx",
                "workflow_version": "1",
                "run_metadata": {"tenant": "acme"},
                "experiment": {"lane": "a"},
                "workflow_meta": {"surface": "support"},
            },
        },
        {
            "ts": "2026-03-21T12:00:01+00:00",
            "run_id": "ctx-a",
            "seq": 2,
            "type": "run_failed",
            "payload": {"state": "classify", "error": {"type": "RuntimeError", "message": "bad input"}},
        },
        {
            "ts": "2026-03-21T12:00:02+00:00",
            "run_id": "ctx-a",
            "seq": 3,
            "type": "structured_output_failed",
            "payload": {
                "state": "classify",
                "schema_name": "Decision",
                "stage": "json_decode",
                "structured_output_mode": "prompt_only",
                "error": {"type": "JSONDecodeError", "message": "bad json"},
            },
        },
        {
            "ts": "2026-03-21T12:00:03+00:00",
            "run_id": "ctx-a",
            "seq": 4,
            "type": "run_completed",
            "payload": {"status": "failed"},
        },
    ]
    run_b = [
        {
            "ts": "2026-03-21T12:10:00+00:00",
            "run_id": "ctx-b",
            "seq": 1,
            "type": "run_started",
            "payload": {
                "workflow_name": "ctx",
                "workflow_version": "1",
                "run_metadata": {"tenant": "globex"},
                "experiment": {"lane": "b"},
                "workflow_meta": {"surface": "product"},
            },
        },
        {
            "ts": "2026-03-21T12:10:01+00:00",
            "run_id": "ctx-b",
            "seq": 2,
            "type": "retry_scheduled",
            "payload": {
                "state": "classify",
                "attempt": 1,
                "max_attempts": 2,
                "error": {"type": "TimeoutError", "message": "slow upstream"},
            },
        },
        {
            "ts": "2026-03-21T12:10:02+00:00",
            "run_id": "ctx-b",
            "seq": 3,
            "type": "run_completed",
            "payload": {"status": "completed"},
        },
    ]
    for rid, events in (("ctx-a", run_a), ("ctx-b", run_b)):
        (log_dir / f"{rid}.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

    out_path = tmp_path / "diff.md"
    runner = CliRunner()
    diff = runner.invoke(
        app,
        [
            "report-diff",
            "ctx-a",
            "ctx-b",
            "--log-dir",
            str(log_dir),
            "--format",
            "markdown",
            "--out",
            str(out_path),
        ],
    )

    assert diff.exit_code == 0
    assert out_path.is_file()
    body = out_path.read_text(encoding="utf-8")
    assert "## Run context" in body
    assert "## Failure and pause signals" in body
    assert "### Experiment" in body
    assert "### Run failure" in body
    assert "### Latest structured parse failure" in body
    assert '"tenant": "acme"' in body
    assert '"tenant": "globex"' in body
    assert body.index("## Run context") < body.index("## Failure and pause signals")
    assert "- **attention=**" in body

    md_sup = runner.invoke(
        app,
        [
            "report-diff",
            "ctx-a",
            "ctx-b",
            "--log-dir",
            str(log_dir),
            "--format",
            "markdown",
            "--style",
            "support",
        ],
    )
    assert md_sup.exit_code == 0
    assert md_sup.stdout.index("## Failure and pause signals") < md_sup.stdout.index("## Run context")

    md_st = runner.invoke(
        app,
        [
            "report-diff",
            "ctx-a",
            "ctx-b",
            "--log-dir",
            str(log_dir),
            "--format",
            "markdown",
            "--style",
            "stakeholder",
        ],
    )
    assert md_st.exit_code == 0
    assert "# Run summary (comparison)" in md_st.stdout


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


def test_cli_ci_writes_summary_json(tmp_path: Path) -> None:
    summary = tmp_path / "ci-summary.json"
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
            "--summary-json",
            str(summary),
        ],
    )
    assert r.exit_code == 0
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["schema"] == "replayt.ci_run_summary.v1"
    assert data["workflow"] == "hello_world_tutorial@1"
    assert data["status"] == "completed"
    assert data["run_id"]
    assert data["exit_code"] == 0
    assert data["target"] == "replayt_examples.e01_hello_world:wf"
    assert data["log_dir"] == str(tmp_path.resolve())
    assert data["dry_run"] is False
    assert data["sqlite"] is None
    assert isinstance(data.get("duration_ms"), int)
    assert data["duration_ms"] >= 0
    assert data["replayt_version"] == getattr(replayt, "__version__", "unknown")
    vi = sys.version_info
    assert data["python_version"] == f"{vi.major}.{vi.minor}.{vi.micro}"
    assert data["platform"] == sys.platform


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


def test_cli_resume_hook_receives_workflow_contract_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    hook_out = tmp_path / "resume_hook.json"
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "Path(os.environ['HOOK_OUT']).write_text("
        "json.dumps({"
        "'approval_id': os.environ.get('REPLAYT_APPROVAL_ID'), "
        "'reject': os.environ.get('REPLAYT_REJECT'), "
        "'log_mode': os.environ.get('REPLAYT_LOG_MODE'), "
        "'forbid_full': os.environ.get('REPLAYT_FORBID_LOG_MODE_FULL'), "
        "'redact_keys': json.loads(os.environ['REPLAYT_REDACT_KEYS_JSON']), "
        "'contract_sha256': os.environ.get('REPLAYT_WORKFLOW_CONTRACT_SHA256'), "
        "'workflow_name': os.environ.get('REPLAYT_WORKFLOW_NAME'), "
        "'workflow_version': os.environ.get('REPLAYT_WORKFLOW_VERSION'), "
        "'metadata': (json.loads(os.environ['REPLAYT_RUN_METADATA_JSON']) "
        "if os.environ.get('REPLAYT_RUN_METADATA_JSON') else None), "
        "'tags': (json.loads(os.environ['REPLAYT_RUN_TAGS_JSON']) "
        "if os.environ.get('REPLAYT_RUN_TAGS_JSON') else None), "
        "'experiment': (json.loads(os.environ['REPLAYT_RUN_EXPERIMENT_JSON']) "
        "if os.environ.get('REPLAYT_RUN_EXPERIMENT_JSON') else None)"
        "}), encoding='utf-8')"
    )
    exe = json.dumps(sys.executable)
    (tmp_path / ".replaytrc.toml").write_text(
        "forbid_log_mode_full = true\n"
        'redact_keys = ["patient_id"]\n'
        f"resume_hook = [{exe}, \"-c\", {json.dumps(script)}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOOK_OUT", str(hook_out))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            "approval_flow:wf",
            "--log-dir",
            str(tmp_path),
            "--metadata-json",
            '{"deployment_tier":"staging"}',
            "--tag",
            "gate=hr",
            "--experiment-json",
            '{"lane":"policy"}',
        ],
    )
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    resume = runner.invoke(
        app,
        ["resume", "approval_flow:wf", run_id, "--approval", "ship", "--log-dir", str(tmp_path)],
    )
    assert resume.exit_code == 0
    data = json.loads(hook_out.read_text(encoding="utf-8"))
    assert data["approval_id"] == "ship"
    assert data["reject"] == "0"
    exp = load_target("approval_flow:wf").contract()
    assert data["contract_sha256"] == exp["contract_sha256"]
    assert data["workflow_name"] == exp["workflow"]["name"]
    assert data["workflow_version"] == exp["workflow"]["version"]
    assert data["metadata"] == {"deployment_tier": "staging"}
    assert data["tags"] == {"gate": "hr"}
    assert data["experiment"] == {"lane": "policy"}
    assert data["log_mode"] == "redacted"
    assert data["forbid_full"] == "1"
    assert data["redact_keys"] == ["patient_id"]


def test_cli_run_hook_receives_policy_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook_out = tmp_path / "run_hook.json"
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "Path(os.environ['HOOK_OUT']).write_text("
        "json.dumps({"
        "'run_id': os.environ.get('REPLAYT_RUN_ID'), "
        "'mode': os.environ.get('REPLAYT_RUN_MODE'), "
        "'target': os.environ.get('REPLAYT_TARGET'), "
        "'dry_run': os.environ.get('REPLAYT_DRY_RUN'), "
        "'log_dir': os.environ.get('REPLAYT_LOG_DIR'), "
        "'log_mode': os.environ.get('REPLAYT_LOG_MODE'), "
        "'forbid_full': os.environ.get('REPLAYT_FORBID_LOG_MODE_FULL'), "
        "'redact_keys': json.loads(os.environ['REPLAYT_REDACT_KEYS_JSON']), "
        "'inputs': json.loads(os.environ['REPLAYT_RUN_INPUTS_JSON']), "
        "'tags': json.loads(os.environ['REPLAYT_RUN_TAGS_JSON']), "
        "'metadata': json.loads(os.environ['REPLAYT_RUN_METADATA_JSON']), "
        "'experiment': json.loads(os.environ['REPLAYT_RUN_EXPERIMENT_JSON']), "
        "'contract_sha256': os.environ.get('REPLAYT_WORKFLOW_CONTRACT_SHA256'), "
        "'workflow_name': os.environ.get('REPLAYT_WORKFLOW_NAME'), "
        "'workflow_version': os.environ.get('REPLAYT_WORKFLOW_VERSION'), "
        "'replayt_version': os.environ.get('REPLAYT_REPLAYT_VERSION')"
        "}), encoding='utf-8')"
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.replayt]\n"
        "forbid_log_mode_full = true\n"
        'redact_keys = ["token", "Email"]\n'
        f"run_hook = [{json.dumps(sys.executable)}, \"-c\", {json.dumps(script)}]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOOK_OUT", str(hook_out))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path / "logs"),
            "--inputs-json",
            '{"customer_name":"Sam","policy":{"env":"dev"}}',
            "--input",
            "policy.env=prod",
            "--tag",
            "deployment=prod",
            "--tag",
            "team=platform",
            "--metadata-json",
            '{"change_ticket":"CHG-123","deployment_tier":"prod"}',
            "--experiment-json",
            '{"cohort":"enterprise-policy"}',
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(hook_out.read_text(encoding="utf-8"))
    run_id = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("run_id="))
    assert data["run_id"] == run_id
    assert data["mode"] == "run"
    assert data["target"] == "replayt_examples.e01_hello_world:wf"
    assert data["dry_run"] == "1"
    assert Path(data["log_dir"]) == (tmp_path / "logs").resolve()
    assert data["log_mode"] == "redacted"
    assert data["forbid_full"] == "1"
    assert data["redact_keys"] == ["Email", "token"]
    assert data["inputs"] == {"customer_name": "Sam", "policy": {"env": "prod"}}
    assert data["tags"] == {"deployment": "prod", "team": "platform"}
    assert data["metadata"] == {"change_ticket": "CHG-123", "deployment_tier": "prod"}
    assert data["experiment"] == {"cohort": "enterprise-policy"}
    exp_contract = load_target("replayt_examples.e01_hello_world:wf").contract()
    assert data["contract_sha256"] == exp_contract["contract_sha256"]
    assert data["workflow_name"] == exp_contract["workflow"]["name"]
    assert data["workflow_version"] == exp_contract["workflow"]["version"]
    assert data["replayt_version"] == replayt.__version__
    assert data["mode"] == "run"
    assert data["target"] == "replayt_examples.e01_hello_world:wf"
    assert data["dry_run"] == "1"
    assert data["log_mode"] == "redacted"
    assert data["log_dir"] == str((tmp_path / "logs").resolve())
    events = [
        json.loads(line)
        for line in (tmp_path / "logs" / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(event for event in events if event["type"] == "run_started")
    assert started["payload"]["runtime"]["policy_hooks"]["run"] == {
        "source": "project_config:run_hook",
        "argv0": Path(sys.executable).name,
        "arg_count": 3,
    }


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


def test_cli_run_inputs_json_at_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-json", "@inputs.json"],
    )
    assert r.exit_code == 0


def test_cli_run_inputs_file_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-file", "-"],
        input='{"k": 99}\n',
    )
    assert r.exit_code == 0


def test_cli_run_inputs_json_at_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-json", "@-"],
        input='{"k": 7}\n',
    )
    assert r.exit_code == 0


def test_cli_run_inputs_file_stdin_with_input_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    assert ctx.get("k") == 2
    assert ctx.get("x") == 0
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
            "--log-dir",
            str(tmp_path / "logs"),
            "--inputs-file",
            "-",
            "--input",
            "k=2",
        ],
        input='{"k": 1, "x": 0}\n',
    )
    assert r.exit_code == 0


def test_cli_run_resolves_inputs_from_replayt_inputs_file_stdin_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", "-")
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs")],
        input='{"k": 3}\n',
    )
    assert r.exit_code == 0


def test_cli_config_json_reports_replayt_inputs_file_stdin_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLAYT_INPUTS_FILE", "-")
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["config", "--format", "json"])
    assert r.exit_code == 0
    d = json.loads(r.stdout)
    assert d["run"]["default_inputs_file"] == "-"
    assert d["run"]["default_inputs_file_source"] == "env:REPLAYT_INPUTS_FILE (stdin)"


def test_cli_run_inputs_json_at_file_requires_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-json", "@"],
    )
    assert r.exit_code == 2
    assert "@path form requires a file path" in _strip_ansi(r.stdout + r.stderr)


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


def test_cli_run_invalid_inputs_json_reports_bad_parameter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--inputs-json", "{bad}"],
    )

    assert r.exit_code == 2
    assert r.exception is not None
    assert "inputs must be valid json" in (r.stdout + r.stderr).lower()
    assert "@path" in _strip_ansi(r.stdout + r.stderr).lower()


def test_cli_run_input_flags_build_nested_inputs_and_coerce_json_scalars(tmp_path: Path) -> None:
    wf_path = tmp_path / "v.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("v")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    assert isinstance(ctx.get("count"), int)
    assert isinstance(ctx.get("enabled"), bool)
    assert isinstance(ctx.get("issue"), dict)
    assert isinstance(ctx.get("config"), dict)
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            str(wf_path),
            "--log-dir",
            str(tmp_path / "logs"),
            "--input",
            "customer_name=Sam",
            "--input",
            "count=2",
            "--input",
            "enabled=false",
            "--input",
            "issue.title=Crash on save",
            "--input",
            'config.tags=["alpha","beta"]',
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path / "logs"), "--output", "json"])
    assert inspect.exit_code == 0
    payload = json.loads(inspect.stdout)
    started = next(event for event in payload["events"] if event["type"] == "run_started")
    assert started["payload"]["inputs"] == {
        "customer_name": "Sam",
        "count": 2,
        "enabled": False,
        "issue": {"title": "Crash on save"},
        "config": {"tags": ["alpha", "beta"]},
    }


def test_cli_run_input_flags_merge_and_override_inputs_json(tmp_path: Path) -> None:
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
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            str(wf_path),
            "--log-dir",
            str(tmp_path / "logs"),
            "--inputs-json",
            '{"issue":{"title":"Old","keep":"yes"},"priority":1}',
            "--input",
            "issue.title=New",
            "--input",
            "issue.body=Stacktrace attached",
            "--input",
            "priority=2",
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    inspect = runner.invoke(app, ["inspect", run_id, "--log-dir", str(tmp_path / "logs"), "--output", "json"])
    assert inspect.exit_code == 0
    payload = json.loads(inspect.stdout)
    started = next(event for event in payload["events"] if event["type"] == "run_started")
    assert started["payload"]["inputs"] == {
        "issue": {"title": "New", "keep": "yes", "body": "Stacktrace attached"},
        "priority": 2,
    }


def test_cli_run_input_flags_reject_non_object_path_conflict(tmp_path: Path) -> None:
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
    runner = CliRunner()
    run = runner.invoke(
        app,
        [
            "run",
            str(wf_path),
            "--log-dir",
            str(tmp_path / "logs"),
            "--inputs-json",
            '{"issue":"oops"}',
            "--input",
            "issue.title=Crash",
        ],
    )
    assert run.exit_code == 2
    text = _strip_ansi(run.stdout + run.stderr)
    assert "cannot descend into 'issue'" in text


def test_cli_supports_python_file_target_with_single_nonstandard_workflow_name(tmp_path: Path) -> None:
    workflow_path = tmp_path / "mini_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

demo_flow = Workflow("mini")
demo_flow.set_initial("start")

@demo_flow.step("start")
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


def test_cli_rejects_python_file_with_multiple_nonstandard_workflows(tmp_path: Path) -> None:
    workflow_path = tmp_path / "multi_flow.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

first = Workflow("one")
first.set_initial("start")

@first.step("start")
def start(ctx):
    return None

second = Workflow("two")
second.set_initial("start")

@second.step("start")
def start_two(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])
    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "multiple Workflow objects" in text
    assert "rename the one you want to `wf` or `workflow`" in text


def test_cli_python_file_target_missing_dependency_shows_onboarding_hints(tmp_path: Path) -> None:
    workflow_path = tmp_path / "broken_import.py"
    workflow_path.write_text(
        """
from missing_demo_dependency import nope
from replayt.workflow import Workflow

wf = Workflow("broken")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])

    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "Importing Python workflow file" in text
    assert "missing_demo_dependency" in text
    assert "pip install -e ." in text
    assert "MODULE:VAR" in text
    assert "doctor --skip-connectivity --target" in text


def test_cli_python_file_target_syntax_error_reports_location(tmp_path: Path) -> None:
    workflow_path = tmp_path / "broken_syntax.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("broken")
wf.set_initial("start")

@wf.step("start")
def start(ctx)
    return None
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["run", str(workflow_path), "--log-dir", str(tmp_path)])

    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "syntax error" in text.lower()
    assert "line 7" in text
    assert "python -m py_compile" in text


def test_cli_run_target_missing_py_suffix_points_at_sibling_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wf_path = tmp_path / "workflow.py"
    wf_path.write_text(
        """
from replayt.workflow import Workflow
wf = Workflow("w")
wf.set_initial("a")
@wf.step("a")
def a(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["run", "workflow", "--log-dir", str(tmp_path / "logs")])
    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "workflow.py" in text
    assert "replayt run" in text


def test_cli_run_target_dotted_without_colon_suggests_module_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "replayt_examples.e01_hello_world", "--log-dir", str(tmp_path / "logs")],
    )
    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "replayt_examples.e01_hello_world:wf" in text
    assert "doctor --skip-connectivity" in text


def test_cli_run_target_directory_rejected_with_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "pkg"
    d.mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["run", "pkg", "--log-dir", str(tmp_path / "logs")])
    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "directory" in text.lower()


def test_cli_run_target_non_workflow_file_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("hello", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    # Use a resolved path so Windows drive-letter ":" does not misparse as MODULE:VAR.
    result = runner.invoke(app, ["run", str(f.resolve()), "--log-dir", str(tmp_path / "logs")])
    assert result.exit_code == 2
    text = _strip_ansi(result.stdout + result.stderr)
    assert "not a supported workflow file" in text.lower()


def test_cli_run_invalid_metadata_and_experiment_json_report_bad_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    bad_meta = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--metadata-json", "{bad}"],
    )
    bad_exp = runner.invoke(
        app,
        ["run", str(wf_path), "--log-dir", str(tmp_path / "logs"), "--experiment-json", "{bad}"],
    )

    assert bad_meta.exit_code == 2
    assert "--metadata-json must be valid json" in _strip_ansi(bad_meta.stdout + bad_meta.stderr).lower()
    assert bad_exp.exit_code == 2
    assert "--experiment-json must be valid json" in _strip_ansi(bad_exp.stdout + bad_exp.stderr).lower()


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


def test_cli_validate_accepts_repeatable_input_flags(tmp_path: Path) -> None:
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
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "validate",
            str(wf_path),
            "--input",
            "issue.title=Crash",
            "--input",
            "priority=2",
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["ok"] is True


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


def test_cli_ci_appends_step_summary_via_replayt_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "nested" / "step_summary.md"
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("REPLAYT_STEP_SUMMARY", str(summary))
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


def test_cli_ci_github_step_summary_wins_over_replayt_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh_file = tmp_path / "gh_summary.md"
    rt_file = tmp_path / "rt_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(gh_file))
    monkeypatch.setenv("REPLAYT_STEP_SUMMARY", str(rt_file))
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
    assert "## replayt ci" in gh_file.read_text(encoding="utf-8")
    assert not rt_file.is_file()


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


def test_cli_run_summary_json_via_replayt_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "from_env_summary.json"
    monkeypatch.setenv("REPLAYT_SUMMARY_JSON", str(summary))
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
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["schema"] == "replayt.ci_run_summary.v1"
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["target"] == "replayt_examples.e01_hello_world:wf"
    assert data["replayt_version"] == getattr(replayt, "__version__", "unknown")
    assert data["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert data["platform"] == sys.platform


def test_cli_summary_json_merges_ci_metadata_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.json"
    monkeypatch.setenv(
        "REPLAYT_CI_METADATA_JSON",
        '{"pipeline_url":"https://ci.example/job/1","commit":"abc"}',
    )
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
            "--summary-json",
            str(summary),
        ],
    )
    assert r.exit_code == 0
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["ci_metadata"] == {"pipeline_url": "https://ci.example/job/1", "commit": "abc"}
    assert data["replayt_version"]
    assert data["python_version"]
    assert data["platform"] == sys.platform


def test_cli_summary_json_rejects_invalid_ci_metadata_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.json"
    monkeypatch.setenv("REPLAYT_SUMMARY_JSON", str(summary))
    monkeypatch.setenv("REPLAYT_CI_METADATA_JSON", "[1,2]")
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
    assert r.exit_code == 1
    assert "REPLAYT_CI_METADATA_JSON" in (r.stdout + r.stderr)
    assert not summary.exists()


def test_cli_ci_metadata_json_ignored_when_no_summary_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPLAYT_CI_METADATA_JSON", "not-json")
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
    assert data["resolved_paths"]["log_dir"]
    approval_reason = next(check for check in data["checks"] if check["name"] == "approval_reason_policy")
    assert approval_reason["ok"] is False
    assert "written justification" in approval_reason["detail"]
    cred = data["credential_env"]
    assert isinstance(cred, list) and cred
    assert len(cred) == len({r["name"] for r in cred})
    assert all("present" in r for r in cred)


def test_cli_doctor_json_soft_warns_extra_provider_credential_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "placeholder")
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["healthy"] is True
    extra = next(c for c in data["checks"] if c["name"] == "credential_env_extra_providers")
    assert extra["ok"] is False
    assert "MISTRAL_API_KEY" in extra["detail"]
    mistral = next(r for r in data["credential_env"] if r["name"] == "MISTRAL_API_KEY")
    assert mistral["present"] is True


def test_cli_config_json_includes_llm_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    runner = CliRunner()
    r = runner.invoke(app, ["config", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    ce = data["llm"]["credential_env"]
    assert isinstance(ce, list) and ce
    names = [r["name"] for r in ce]
    assert "OPENAI_API_KEY" in names
    assert "COHERE_API_KEY" in names


def test_cli_version_text() -> None:
    import replayt as rt

    runner = CliRunner()
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert rt.__version__ in r.stdout
    assert "python" in r.stdout.lower()
    assert "platform" in r.stdout.lower()


def test_cli_version_format_json() -> None:
    import replayt as rt
    from replayt.cli.config import SUPPORTED_CONFIG_KEYS

    runner = CliRunner()
    r = runner.invoke(app, ["version", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["schema"] == "replayt.version_report.v1"
    assert data["replayt_version"] == rt.__version__
    assert data["platform"] == sys.platform
    assert data["supported_project_config_keys"] == sorted(SUPPORTED_CONFIG_KEYS)
    from replayt.cli.main import app as cli_app

    assert data["cli_subcommands"] == sorted(
        c.name for c in cli_app.registered_commands if c.name
    )
    maint = data["maintainer_script_schemas"]
    assert maint["unreleased_changelog"] == "replayt.unreleased_changelog.v1"
    assert maint["changelog_gate_policy"] == "replayt.changelog_gate_policy.v1"
    assert maint["docs_index_report"] == "replayt.docs_index_report.v1"
    assert maint["version_consistency"] == "replayt.version_consistency.v1"
    assert maint["pyproject_pep621"] == "replayt.pyproject_pep621_report.v1"
    assert maint["example_catalog_contract"] == "replayt.example_catalog_contract.v1"
    assert maint["public_api_report"] == "replayt.public_api_report.v1"
    assert maint["maintainer_checks"] == "replayt.maintainer_checks.v1"
    assert maint["skill_invocation"] == "replayt.skill_invocation.v1"
    assert maint["skill_release_pipeline"] == "replayt.skill_release_pipeline.v1"
    py = data["python"]
    assert py["version"] == f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    schemas = data["cli_machine_readable_schemas"]
    assert schemas["version_report"] == "replayt.version_report.v1"
    assert schemas["validate_report"] == "replayt.validate_report.v1"
    assert schemas["workflow_contract"] == "replayt.workflow_contract.v1"
    assert schemas["workflow_contract_check"] == "replayt.workflow_contract_check.v1"
    assert schemas["run_result"] == "replayt.run_result.v1"
    assert schemas["inspect_report"] == "replayt.inspect_report.v1"
    assert schemas["runs_report"] == "replayt.runs_report.v1"
    assert schemas["stats_report"] == "replayt.stats_report.v1"
    assert schemas["diff_report"] == "replayt.diff_report.v1"
    assert schemas["bundle_export"] == "replayt.bundle_export.v1"
    assert schemas["export_bundle"] == "replayt.export_bundle.v1"
    assert schemas["export_seal"] == "replayt.export_seal.v1"
    assert schemas["seal"] == "replayt.seal.v1"
    assert schemas["verify_seal_report"] == "replayt.verify_seal_report.v1"
    assert schemas["try_examples"] == "replayt.try_examples.v1"
    assert schemas["try_copy"] == "replayt.try_copy.v1"
    assert schemas["init_templates"] == "replayt.init_templates.v1"
    from replayt.cli.run_support import (
        build_cli_exit_codes_report,
        build_cli_json_stdout_contract,
        build_cli_stdio_contract,
    )

    assert data["cli_exit_codes"] == build_cli_exit_codes_report()
    assert data["cli_stdio_contract"] == build_cli_stdio_contract()
    assert data["cli_json_stdout_contract"] == build_cli_json_stdout_contract()
    from replayt.cli.path_readiness import build_operational_paths_report

    assert data["operational_paths"] == build_operational_paths_report()
    assert data["cli_machine_readable_schemas"]["operational_paths"] == "replayt.operational_paths.v1"
    from replayt.cli.distribution_metadata import build_distribution_metadata_report

    assert data["distribution_metadata"] == build_distribution_metadata_report()
    assert data["cli_machine_readable_schemas"]["distribution_metadata"] == "replayt.distribution_metadata.v1"
    ph = data["policy_hook_env_catalog"]
    assert ph["subprocess_stdin"] == "devnull"
    hooks = ph["hooks"]
    assert set(hooks) == {"export_hook", "resume_hook", "run_hook", "seal_hook", "verify_seal_hook"}
    rh = hooks["run_hook"]
    assert rh["argv_env"] == "REPLAYT_RUN_HOOK"
    assert rh["argv_config_key"] == "run_hook"
    assert "REPLAYT_REPLAYT_VERSION" in rh["injected_env_vars"]
    assert "REPLAYT_TARGET" in rh["injected_env_vars"]
    assert "REPLAYT_FORBID_LOG_MODE_FULL" in rh["injected_env_vars"]
    assert "REPLAYT_REDACT_KEYS_JSON" in rh["injected_env_vars"]
    assert "REPLAYT_WORKFLOW_CONTRACT_SHA256" in rh["injected_env_vars"]
    vh = hooks["verify_seal_hook"]
    assert vh["argv_env"] == "REPLAYT_VERIFY_SEAL_HOOK"
    assert "REPLAYT_VERIFY_SEAL_FILE_SHA256" in vh["injected_env_vars"]
    assert "REPLAYT_WORKFLOW_CONTRACT_SHA256" in vh["injected_env_vars"]
    eh = hooks["export_hook"]
    assert "REPLAYT_TARGET" in eh["injected_env_vars"]
    assert "REPLAYT_WORKFLOW_NAME" in eh["injected_env_vars"]
    assert "REPLAYT_RUN_METADATA_JSON" in eh["injected_env_vars"]
    assert "REPLAYT_RUN_TAGS_JSON" in eh["injected_env_vars"]
    assert "REPLAYT_RUN_EXPERIMENT_JSON" in eh["injected_env_vars"]
    sh = hooks["seal_hook"]
    assert "REPLAYT_WORKFLOW_VERSION" in sh["injected_env_vars"]
    assert "REPLAYT_RUN_METADATA_JSON" in sh["injected_env_vars"]
    assert "REPLAYT_RUN_TAGS_JSON" in sh["injected_env_vars"]
    assert "REPLAYT_RUN_EXPERIMENT_JSON" in sh["injected_env_vars"]
    res_h = hooks["resume_hook"]
    assert "REPLAYT_LOG_MODE" in res_h["injected_env_vars"]
    assert "REPLAYT_FORBID_LOG_MODE_FULL" in res_h["injected_env_vars"]
    assert "REPLAYT_REDACT_KEYS_JSON" in res_h["injected_env_vars"]
    assert "REPLAYT_RUN_METADATA_JSON" in res_h["injected_env_vars"]
    assert "REPLAYT_RUN_TAGS_JSON" in res_h["injected_env_vars"]
    assert "REPLAYT_RUN_EXPERIMENT_JSON" in res_h["injected_env_vars"]
    assert "REPLAYT_RUN_METADATA_JSON" in vh["injected_env_vars"]
    assert "REPLAYT_RUN_TAGS_JSON" in vh["injected_env_vars"]
    assert "REPLAYT_RUN_EXPERIMENT_JSON" in vh["injected_env_vars"]
    from replayt.cli.config import build_project_config_discovery_report

    assert data["project_config_discovery"] == build_project_config_discovery_report()
    assert data["cli_machine_readable_schemas"]["project_config_discovery"] == "replayt.project_config_discovery.v1"


def test_run_started_hook_json_blobs_from_jsonl_path_finds_first_after_prefix(tmp_path: Path) -> None:
    from replayt.cli.run_support import run_started_hook_json_blobs_from_jsonl_path

    log = tmp_path / "run.jsonl"
    log.write_text(
        '{"type":"state_entered","payload":{"state":"x"}}\n'
        '{"type":"run_started","payload":{'
        '"run_metadata":{"k":"v"},"tags":{"a":"b"},"experiment":{"n":1}'
        "}}\n"
        '{"not": "valid json"}\n',
        encoding="utf-8",
    )
    meta_j, tags_j, exp_j = run_started_hook_json_blobs_from_jsonl_path(log)
    assert meta_j is not None and json.loads(meta_j) == {"k": "v"}
    assert tags_j is not None and json.loads(tags_j) == {"a": "b"}
    assert exp_j is not None and json.loads(exp_j) == {"n": 1}


def test_run_started_hook_json_blobs_from_jsonl_path_invalid_utf8_returns_none(tmp_path: Path) -> None:
    from replayt.cli.run_support import run_started_hook_json_blobs_from_jsonl_path

    log = tmp_path / "bad.jsonl"
    log.write_bytes(b"\xff\xfe\n")
    assert run_started_hook_json_blobs_from_jsonl_path(log) == (None, None, None)


def test_cli_version_operational_paths_respects_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_project_config_cache()
    monkeypatch.chdir(tmp_path)
    custom_log = tmp_path / "my_logs"
    monkeypatch.setenv("REPLAYT_LOG_DIR", str(custom_log))
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("REPLAYT_JUNIT_XML", str(tmp_path / "out.xml"))
    monkeypatch.setenv("REPLAYT_SUMMARY_JSON", str(tmp_path / "sum.json"))
    try:
        runner = CliRunner()
        r = runner.invoke(app, ["version", "--format", "json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        op = data["operational_paths"]
        assert op["schema"] == "replayt.operational_paths.v1"
        assert op["cwd"] == str(tmp_path.resolve())
        assert op["effective_log_dir"] == str(custom_log.resolve())
        assert op["step_summary"]["path"] == str(summary_file.resolve())
        assert op["step_summary"]["path_source"] == "env:GITHUB_STEP_SUMMARY"
        assert op["ci_artifact_paths"]["junit_xml"] == str((tmp_path / "out.xml").resolve())
        assert op["ci_artifact_paths"]["summary_json"] == str((tmp_path / "sum.json").resolve())
    finally:
        _reset_project_config_cache()


def test_python_m_replayt_invokes_cli(tmp_path: Path) -> None:
    import replayt as rt

    repo_root = Path(__file__).resolve().parents[1]
    src = str(repo_root / "src")
    env = {**os.environ, "PYTHONPATH": src}
    proc = subprocess.run(
        [sys.executable, "-m", "replayt", "version", "--format", "json"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    data = json.loads(proc.stdout)
    assert data["schema"] == "replayt.version_report.v1"
    assert data["replayt_version"] == rt.__version__
    dm = data["distribution_metadata"]
    assert dm["schema"] == "replayt.distribution_metadata.v1"
    assert isinstance(dm["ok"], bool)
    assert "detail" in dm
    if dm["ok"]:
        assert isinstance(dm["version"], str) and dm["version"].strip()
        assert dm["requires_python"] is not None
    else:
        assert dm["version"] is None
        assert dm["requires_python"] is None


def test_cli_doctor_target_preflight_reports_validation(tmp_path: Path) -> None:
    workflow_path = tmp_path / "doctor_target.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("doctor_target")
wf.set_initial("start")
wf.note_transition("start", "done")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["doctor", "--skip-connectivity", "--format", "json", "--target", str(workflow_path), "--strict-graph"],
    )
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["healthy"] is True
    assert data["target"]["ok"] is True
    assert data["target"]["workflow"]["name"] == "doctor_target"


def test_cli_doctor_target_preflight_fails_invalid_target(tmp_path: Path) -> None:
    workflow_path = tmp_path / "doctor_bad_target.py"
    workflow_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("doctor_bad_target")
wf.set_initial("start")

@wf.step("start")
def start(ctx):
    return "done"

@wf.step("done")
def done(ctx):
    return None
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["doctor", "--skip-connectivity", "--format", "json", "--target", str(workflow_path), "--strict-graph"],
    )
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["healthy"] is False
    assert data["target"]["ok"] is False
    assert any("strict graph" in err.lower() for err in data["target"]["errors"])


def test_cli_doctor_reports_invalid_anthropic_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAYT_PROVIDER", "anthropic")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["healthy"] is False
    provider_config = next(check for check in data["checks"] if check["name"] == "provider_config")
    assert provider_config["ok"] is False
    assert "OPENAI_BASE_URL" in provider_config["detail"]


def test_cli_doctor_reports_soft_trust_boundary_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://api.example.test/v1?token=secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["healthy"] is True
    transport = next(check for check in data["checks"] if check["name"] == "trust_base_url_transport")
    embedded = next(check for check in data["checks"] if check["name"] == "trust_base_url_credentials")
    assert transport["ok"] is False
    assert "plaintext http" in transport["detail"].lower()
    assert embedded["ok"] is False
    assert "query params token" in embedded["detail"].lower()


def test_cli_doctor_soft_warns_on_world_readable_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=x\n", encoding="utf-8")
    env_file.chmod(0o666)
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["healthy"] is True
    dot_r = next(c for c in data["checks"] if c["name"] == "trust_dotenv_other_readable")
    dot_w = next(c for c in data["checks"] if c["name"] == "trust_dotenv_other_writable")
    assert dot_r["ok"] is False
    assert dot_w["ok"] is False
    assert str(env_file) in dot_r["detail"]


def test_cli_doctor_reports_policy_hooks_as_soft_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nrun_hook = [{json.dumps(sys.executable)}, \"-c\", \"print('ok')\"]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["healthy"] is True
    policy_hooks = next(check for check in data["checks"] if check["name"] == "policy_hooks_external_code")
    assert policy_hooks["ok"] is False
    assert "run_hook" in policy_hooks["detail"]
    assert Path(sys.executable).name in policy_hooks["detail"]


def test_cli_doctor_reports_unusable_log_dir_from_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "blocked-parent"
    blocked.write_text("not a dir", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.replayt]\nlog_dir = "{blocked.name}/runs"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    log_dir_ready = next(check for check in data["checks"] if check["name"] == "log_dir_ready")
    assert log_dir_ready["ok"] is False
    assert "not a directory" in log_dir_ready["detail"].lower()


def test_cli_doctor_reports_unusable_summary_json_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "blocked-parent"
    blocked.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv("REPLAYT_SUMMARY_JSON", str(blocked / "summary.json"))
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    check = next(item for item in data["checks"] if item["name"] == "ci_summary_json_ready")
    assert check["ok"] is False
    assert "not a directory" in check["detail"].lower()
    assert data["ci_artifacts"]["summary_json"]["source"] == "env:REPLAYT_SUMMARY_JSON"


def test_cli_doctor_reports_missing_github_step_summary_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAYT_GITHUB_SUMMARY", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("REPLAYT_STEP_SUMMARY", raising=False)
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    check = next(item for item in data["checks"] if item["name"] == "ci_github_summary_ready")
    assert check["ok"] is False
    assert "github_step_summary" in check["detail"].lower()
    assert "replayt_step_summary" in check["detail"].lower()
    assert data["ci_artifacts"]["github_summary"]["requested"] is True
    assert data["ci_artifacts"]["github_summary"]["path"] is None


def test_cli_doctor_and_config_preflight_replayt_step_summary_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "ci-summary.md"
    monkeypatch.setenv("REPLAYT_GITHUB_SUMMARY", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("REPLAYT_STEP_SUMMARY", str(summary))
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    check = next(item for item in data["checks"] if item["name"] == "ci_github_summary_ready")
    assert check["ok"] is True
    assert data["ci_artifacts"]["github_summary"]["path"] == str(summary.resolve())
    assert data["ci_artifacts"]["github_summary"]["path_source"] == "env:REPLAYT_STEP_SUMMARY"

    r2 = runner.invoke(app, ["config", "--format", "json"])
    assert r2.exit_code == 0
    cfg_data = json.loads(r2.stdout)
    assert cfg_data["ci_artifacts"]["github_summary"]["path"] == str(summary.resolve())
    assert cfg_data["ci_artifacts"]["github_summary"]["path_source"] == "env:REPLAYT_STEP_SUMMARY"


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
        man_m = next(name for name in names if name.endswith("/manifest.json"))
        man = json.loads(tf.extractfile(man_m).read().decode("utf-8"))
    assert man.get("timeline_style") == "stakeholder"


def test_cli_bundle_export_support_report_style(tmp_path: Path) -> None:
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
    out_tar = tmp_path / "support-bundle.tar.gz"
    be = runner.invoke(
        app,
        [
            "bundle-export",
            run_id,
            "--out",
            str(out_tar),
            "--log-dir",
            str(tmp_path),
            "--report-style",
            "support",
        ],
    )
    assert be.exit_code == 0
    with tarfile.open(out_tar, "r:gz") as tf:
        report_member = next(name for name in tf.getnames() if name.endswith("/report.html"))
        report_html = tf.extractfile(report_member).read().decode("utf-8")
        timeline_member = next(name for name in tf.getnames() if name.endswith("/timeline.html"))
        timeline_html = tf.extractfile(timeline_member).read().decode("utf-8")
        man_m = next(name for name in tf.getnames() if name.endswith("/manifest.json"))
        man = json.loads(tf.extractfile(man_m).read().decode("utf-8"))
    assert "Support handoff" in report_html
    assert "Support handoff" in timeline_html
    assert man.get("timeline_style") == "support"


def test_cli_bundle_export_can_include_seal(tmp_path: Path) -> None:
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
    out_tar = tmp_path / "sealed-bundle.tar.gz"
    be = runner.invoke(
        app,
        ["bundle-export", run_id, "--out", str(out_tar), "--log-dir", str(tmp_path), "--seal"],
    )
    assert be.exit_code == 0
    with tarfile.open(out_tar, "r:gz") as tf:
        seal_member = next(name for name in tf.getnames() if name.endswith("/events.seal.json"))
        seal_data = json.loads(tf.extractfile(seal_member).read().decode("utf-8"))
    assert seal_data["schema"] == "replayt.export_seal.v1"
    assert seal_data["run_id"] == run_id
    assert seal_data["jsonl_path"] == "events.jsonl"


def test_cli_bundle_export_target_adds_contract_snapshot(tmp_path: Path) -> None:
    runner = CliRunner()
    target = "replayt_examples.e01_hello_world:wf"
    run = runner.invoke(
        app,
        [
            "run",
            target,
            "--log-dir",
            str(tmp_path),
            "--inputs-json",
            '{"customer_name":"x"}',
        ],
    )
    assert run.exit_code == 0
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))
    out_tar = tmp_path / "contract-bundle.tar.gz"
    export = runner.invoke(
        app,
        [
            "bundle-export",
            run_id,
            "--out",
            str(out_tar),
            "--log-dir",
            str(tmp_path),
            "--target",
            target,
        ],
    )
    assert export.exit_code == 0

    with tarfile.open(out_tar, "r:gz") as tf:
        names = tf.getnames()
        assert any(name.endswith("/workflow.contract.json") for name in names)
        assert any(name.endswith("/workflow.mmd.txt") for name in names)
        manifest_member = next(name for name in names if name.endswith("/manifest.json"))
        manifest = json.loads(tf.extractfile(manifest_member).read().decode("utf-8"))
        contract_member = next(name for name in names if name.endswith("/workflow.contract.json"))
        contract = json.loads(tf.extractfile(contract_member).read().decode("utf-8"))

    assert manifest["run_summary"]["workflow_name"] == "hello_world_tutorial"
    assert manifest["run_summary"]["status"] == "completed"
    assert manifest["workflow_contract_snapshot"] == {
        "target": target,
        "file": "workflow.contract.json",
        "contract_sha256": contract["contract_sha256"],
        "matches_run_started": True,
        "mermaid_file": "workflow.mmd.txt",
    }


def test_cli_resume_reason_and_actor_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.replayt]\nresume_hook = [{json.dumps(sys.executable)}, \"-c\", \"print('ok')\"]\n",
        encoding="utf-8",
    )
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)
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
    assert p["policy_hook"] == {
        "source": "project_config:resume_hook",
        "argv0": Path(sys.executable).name,
        "arg_count": 3,
    }


def test_cli_resume_invalid_actor_json_reports_bad_parameter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "approval_flow.py"
    module_path.write_text(
        """
from replayt.workflow import Workflow

wf = Workflow("approval_flow")
wf.set_initial("gate")

@wf.step("gate")
def gate(ctx):
    ctx.request_approval("ship", summary="Ship it?")
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
            "--actor-json",
            "{bad}",
        ],
    )

    assert resume.exit_code == 2
    assert "--actor-json must be valid json" in _strip_ansi(resume.stdout + resume.stderr).lower()


def test_cli_resume_enforces_required_actor_keys_from_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\napproval_actor_required_keys = ["email", "ticket_id"]\n',
        encoding="utf-8",
    )
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    run = runner.invoke(app, ["run", "approval_flow:wf", "--log-dir", str(tmp_path / "logs")])
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    missing = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--actor-json",
            '{"email":"a@example.com"}',
        ],
    )
    assert missing.exit_code == 1
    assert "missing required keys: ticket_id" in _strip_ansi(missing.stdout + missing.stderr).lower()

    ok = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--actor-json",
            '{"email":"a@example.com","ticket_id":"T-1"}',
        ],
    )
    assert ok.exit_code == 0


def test_cli_resume_require_reason_flag_enforces_non_empty_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = CliRunner()
    run = runner.invoke(app, ["run", "approval_flow:wf", "--log-dir", str(tmp_path / "logs")])
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    missing = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--require-reason",
        ],
    )
    assert missing.exit_code == 1
    assert "approval reason is required" in _strip_ansi(missing.stdout + missing.stderr).lower()

    blank = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--require-reason",
            "--reason",
            "   ",
        ],
    )
    assert blank.exit_code == 1
    assert "approval reason is required" in _strip_ansi(blank.stdout + blank.stderr).lower()

    ok = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--require-reason",
            "--reason",
            "Approved after CAB review",
        ],
    )
    assert ok.exit_code == 0


def test_cli_resume_enforces_required_reason_from_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\napproval_reason_required = true\n',
        encoding="utf-8",
    )
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)

    runner = CliRunner()
    doctor = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert doctor.exit_code == 0
    doctor_data = json.loads(doctor.stdout)
    approval_reason = next(check for check in doctor_data["checks"] if check["name"] == "approval_reason_policy")
    assert approval_reason["ok"] is True
    assert "project_config:approval_reason_required" in approval_reason["detail"]

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    config_data = json.loads(config.stdout)
    assert config_data["resume"]["required_reason"] is True
    assert config_data["resume"]["required_reason_source"] == "project_config:approval_reason_required"

    run = runner.invoke(app, ["run", "approval_flow:wf", "--log-dir", str(tmp_path / "logs")])
    assert run.exit_code == 2
    run_id = next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("run_id="))

    missing = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    assert missing.exit_code == 1
    assert "approval reason is required" in _strip_ansi(missing.stdout + missing.stderr).lower()

    ok = runner.invoke(
        app,
        [
            "resume",
            "approval_flow:wf",
            run_id,
            "--approval",
            "ship",
            "--log-dir",
            str(tmp_path / "logs"),
            "--reason",
            "Approved under change ticket CAB-42",
        ],
    )
    assert ok.exit_code == 0


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
    assert data["schema"] == "replayt.stats_report.v1"
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


def test_cli_gc_deletes_sqlite_only_runs(tmp_path: Path) -> None:
    from replayt.persistence import SQLiteStore

    log_dir = tmp_path / "runs"
    db_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(db_path)
    try:
        store.append_event(
            "sqlite-old",
            ts="2000-01-01T00:00:00+00:00",
            typ="run_started",
            payload={"workflow_name": "w", "workflow_version": "1"},
        )
        store.append_event(
            "sqlite-old",
            ts="2000-01-02T00:00:00+00:00",
            typ="run_completed",
            payload={"status": "completed"},
        )
    finally:
        store.close()

    runner = CliRunner()
    out = runner.invoke(
        app,
        ["gc", "--log-dir", str(log_dir), "--sqlite", str(db_path), "--older-than", "1d"],
    )
    assert out.exit_code == 0
    assert "deleted sqlite-old" in out.stdout

    store = SQLiteStore(db_path)
    try:
        assert store.load_events("sqlite-old") == []
    finally:
        store.close()


def test_cli_gc_rejects_missing_sqlite_without_creating_database(tmp_path: Path) -> None:
    log_dir = tmp_path / "runs"
    missing_db = tmp_path / "missing.sqlite3"
    runner = CliRunner()

    out = runner.invoke(
        app,
        ["gc", "--log-dir", str(log_dir), "--sqlite", str(missing_db), "--older-than", "1d"],
    )

    assert out.exit_code == 1
    assert "sqlite store not found" in (out.stdout + out.stderr).lower()
    assert not missing_db.exists()


def test_cli_read_store_uses_read_only_sqlite_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from replayt.cli import stores as stores_mod

    db = tmp_path / "events.sqlite3"
    db.write_text("", encoding="utf-8")
    calls: list[tuple[Path, bool]] = []

    class _FakeStore:
        def __init__(self, path: Path, *, read_only: bool = False) -> None:
            calls.append((path, read_only))

        def close(self) -> None:
            return None

    monkeypatch.setattr(stores_mod, "SQLiteStore", _FakeStore)

    with stores_mod.read_store(tmp_path, db):
        pass

    assert calls == [(db, True)]


def test_cli_config_and_doctor_sanitize_base_url_with_embedded_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "super-secret"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", f"https://user:{secret}@api.example.test/v1?token={secret}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    assert secret not in config.stdout
    config_data = json.loads(config.stdout)
    assert config_data["llm"]["base_url"] == "https://api.example.test/v1"
    config_warnings = config_data["trust_boundary"]["warnings"]
    assert any("user-info credentials" in warning for warning in config_warnings)
    assert any("query params token" in warning.lower() for warning in config_warnings)

    doctor = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert doctor.exit_code == 0
    assert secret not in doctor.stdout
    doctor_data = json.loads(doctor.stdout)
    openai_base_url = next(check for check in doctor_data["checks"] if check["name"] == "openai_base_url")
    embedded = next(check for check in doctor_data["checks"] if check["name"] == "trust_base_url_credentials")
    assert openai_base_url["detail"] == "https://api.example.test/v1 (env:OPENAI_BASE_URL)"
    assert embedded["ok"] is False
    assert "user-info credentials" in embedded["detail"]
    assert "query params token" in embedded["detail"].lower()


def test_cli_config_and_doctor_warn_on_group_accessible_local_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")

    log_dir = tmp_path / ".replayt" / "runs"
    log_dir.mkdir(parents=True)
    log_dir.chmod(0o770)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    env_file.chmod(0o660)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")

    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    config_data = json.loads(config.stdout)
    config_checks = {check["name"]: check for check in config_data["trust_boundary"]["checks"]}
    assert config_checks["trust_log_dir_group_readable"]["ok"] is False
    assert config_checks["trust_log_dir_group_writable"]["ok"] is False
    assert config_checks["trust_dotenv_group_readable"]["ok"] is False
    assert config_checks["trust_dotenv_group_writable"]["ok"] is False

    doctor = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert doctor.exit_code == 0
    doctor_data = json.loads(doctor.stdout)
    doctor_checks = {check["name"]: check for check in doctor_data["checks"]}
    assert doctor_checks["trust_log_dir_group_readable"]["ok"] is False
    assert doctor_checks["trust_log_dir_group_writable"]["ok"] is False
    assert doctor_checks["trust_dotenv_group_readable"]["ok"] is False
    assert doctor_checks["trust_dotenv_group_writable"]["ok"] is False


def test_cli_doctor_and_config_warn_on_permissive_workflow_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")

    wf_py = tmp_path / "wf.py"
    wf_py.write_text(
        """from replayt.workflow import Workflow

wf = Workflow(\"t\", version=\"1\")
wf.set_initial(\"a\")
wf.note_transition(\"a\", \"b\")

@wf.step(\"a\")
def a(ctx):
    return \"b\"

@wf.step(\"b\")
def b(ctx):
    return None
""",
        encoding="utf-8",
    )
    wf_py.chmod(0o660)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")
    monkeypatch.setenv("REPLAYT_TARGET", str(wf_py))

    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()

    doctor = runner.invoke(
        app,
        ["doctor", "--skip-connectivity", "--format", "json", "--target", str(wf_py)],
    )
    assert doctor.exit_code == 0
    doctor_data = json.loads(doctor.stdout)
    doctor_checks = {c["name"]: c for c in doctor_data["checks"]}
    assert doctor_checks["trust_workflow_entry_group_readable"]["ok"] is False
    assert doctor_checks["trust_workflow_entry_group_writable"]["ok"] is False

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    config_data = json.loads(config.stdout)
    config_checks = {c["name"]: c for c in config_data["trust_boundary"]["checks"]}
    assert config_checks["trust_workflow_entry_group_readable"]["ok"] is False
    assert config_checks["trust_workflow_entry_group_writable"]["ok"] is False


def test_cli_doctor_and_config_warn_on_permissive_inputs_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")

    inp = tmp_path / "inputs.json"
    inp.write_text("{}", encoding="utf-8")
    inp.chmod(0o660)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[tool.replayt]\ninputs_file = "{inp.name}"\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")

    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()

    doctor = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert doctor.exit_code == 0
    doctor_data = json.loads(doctor.stdout)
    doctor_checks = {c["name"]: c for c in doctor_data["checks"]}
    assert doctor_checks["trust_inputs_file_group_readable"]["ok"] is False
    assert doctor_checks["trust_inputs_file_group_writable"]["ok"] is False

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    config_data = json.loads(config.stdout)
    config_checks = {c["name"]: c for c in config_data["trust_boundary"]["checks"]}
    assert config_checks["trust_inputs_file_group_readable"]["ok"] is False
    assert config_checks["trust_inputs_file_group_writable"]["ok"] is False


def test_cli_doctor_and_config_warn_on_permissive_policy_hook_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")

    hook = tmp_path / "gate.sh"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o660)
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.replayt]\nrun_hook = "{hook.name}"\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("REPLAYT_PROVIDER", "openai")
    for name in (
        "REPLAYT_RUN_HOOK",
        "REPLAYT_RESUME_HOOK",
        "REPLAYT_EXPORT_HOOK",
        "REPLAYT_SEAL_HOOK",
        "REPLAYT_VERIFY_SEAL_HOOK",
    ):
        monkeypatch.delenv(name, raising=False)

    import replayt.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_PATH", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_UNKNOWN_KEYS", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_SHADOWED_SOURCES", None)
    monkeypatch.setattr(cfg_mod, "_PROJECT_CONFIG_CWD", None)

    runner = CliRunner()

    doctor = runner.invoke(app, ["doctor", "--skip-connectivity", "--format", "json"])
    assert doctor.exit_code == 0
    doctor_data = json.loads(doctor.stdout)
    doctor_checks = {c["name"]: c for c in doctor_data["checks"]}
    assert doctor_checks["trust_policy_hook_script_group_readable"]["ok"] is False
    assert doctor_checks["trust_policy_hook_script_group_writable"]["ok"] is False

    config = runner.invoke(app, ["config", "--format", "json"])
    assert config.exit_code == 0
    config_data = json.loads(config.stdout)
    config_checks = {c["name"]: c for c in config_data["trust_boundary"]["checks"]}
    assert config_checks["trust_policy_hook_script_group_readable"]["ok"] is False
    assert config_checks["trust_policy_hook_script_group_writable"]["ok"] is False


def test_cli_run_timeout_appends_run_interrupted_to_sqlite_mirror(tmp_path: Path, monkeypatch) -> None:
    from replayt.cli.commands import run as run_cmd
    from replayt.persistence import JSONLStore, SQLiteStore

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(run_cmd.subprocess, "run", boom)
    db = tmp_path / "mirror.sqlite3"
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--sqlite",
            str(db),
            "--timeout",
            "1",
            "--run-id",
            "tout1",
            "--dry-run",
        ],
    )
    assert r.exit_code == 1
    assert "timed out" in r.stderr.lower() or "timed out" in r.stdout.lower()

    sql = SQLiteStore(db)
    try:
        ev_sql = sql.load_events("tout1")
        assert any(e["type"] == "run_interrupted" for e in ev_sql)
    finally:
        sql.close()

    ev_j = JSONLStore(tmp_path).load_events("tout1")
    assert any(e["type"] == "run_interrupted" for e in ev_j)


def test_cli_run_timeout_without_run_id_still_records_run_interrupted(tmp_path: Path, monkeypatch) -> None:
    from replayt.cli.commands import run as run_cmd
    from replayt.persistence import JSONLStore

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(run_cmd.subprocess, "run", boom)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--timeout",
            "1",
            "--dry-run",
        ],
    )
    assert r.exit_code == 1
    run_ids = JSONLStore(tmp_path).list_run_ids()
    assert len(run_ids) == 1
    events = JSONLStore(tmp_path).load_events(run_ids[0])
    assert any(e["type"] == "run_interrupted" for e in events)


def test_cli_run_timeout_logs_when_run_interrupted_append_fails(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    import logging

    from replayt.cli.commands import run as run_cmd

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    class _OpenStoreFails:
        def __enter__(self):
            raise OSError("simulated store open failure")

        def __exit__(self, *exc: object) -> None:
            return None

    def fake_open_store(*_a, **_k):
        return _OpenStoreFails()

    monkeypatch.setattr(run_cmd.subprocess, "run", boom)
    monkeypatch.setattr(run_cmd, "open_store", fake_open_store)

    caplog.set_level(logging.WARNING)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--log-dir",
            str(tmp_path),
            "--timeout",
            "1",
            "--run-id",
            "append-fail1",
            "--dry-run",
        ],
    )
    assert r.exit_code == 1
    assert any(
        "Could not append run_interrupted after parent subprocess timeout" in rec.message
        for rec in caplog.records
    )


def test_subprocess_env_child_adds_src_layout_to_pythonpath(tmp_path: Path, monkeypatch) -> None:
    from replayt.cli.run_support import subprocess_env_child

    pkg_dir = tmp_path / "src" / "replayt"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")

    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    monkeypatch.delenv("PYTHONPATH", raising=False)

    env = subprocess_env_child()

    assert env["PYTHONPATH"] == str(tmp_path / "src")


def test_cli_forbid_log_mode_full_env_blocks_run_dry_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _reset_project_config_cache()
    monkeypatch.setenv("REPLAYT_FORBID_LOG_MODE_FULL", "1")
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--dry-check",
            "--log-mode",
            "full",
            "--inputs-json",
            '{"customer_name":"Pat"}',
        ],
    )
    assert r.exit_code != 0
    out = _strip_ansi(r.stdout) + _strip_ansi(r.stderr)
    assert "log_mode=full is forbidden" in out


def test_cli_forbid_log_mode_full_env_false_overrides_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\nforbid_log_mode_full = true\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _reset_project_config_cache()
    monkeypatch.setenv("REPLAYT_FORBID_LOG_MODE_FULL", "false")
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "run",
            "replayt_examples.e01_hello_world:wf",
            "--dry-check",
            "--log-mode",
            "full",
            "--inputs-json",
            '{"customer_name":"Pat"}',
        ],
    )
    assert r.exit_code == 0
    assert "dry check passed" in r.stdout


def test_cli_doctor_json_log_mode_full_forbidden_when_default_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\nforbid_log_mode_full = true\nlog_mode = "full"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _reset_project_config_cache()
    runner = CliRunner()
    r = runner.invoke(app, ["doctor", "--format", "json", "--skip-connectivity"])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    chk = next(c for c in data["checks"] if c["name"] == "log_mode_full_forbidden")
    assert chk["ok"] is False


def test_cli_config_json_includes_log_mode_full_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.replayt]\nforbid_log_mode_full = true\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _reset_project_config_cache()
    runner = CliRunner()
    r = runner.invoke(app, ["config", "--format", "json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["runtime_defaults"]["log_mode_full_forbidden"] is True
    assert data["runtime_defaults"]["log_mode_full_forbidden_source"] == "project_config:forbid_log_mode_full"
