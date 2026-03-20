from __future__ import annotations

from typer.testing import CliRunner

from replayt.cli.main import app


def test_cli_graph_smoke() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["graph", "examples.issue_triage:wf"])
    assert r.exit_code == 0
    assert "flowchart TD" in r.stdout
