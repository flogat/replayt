from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "check_changelog_if_needed.py"
    spec = importlib.util.spec_from_file_location("check_changelog_if_needed", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_is_protected_path() -> None:
    gate = _load_script()
    assert gate.is_protected_path("src/replayt/runner.py")
    assert gate.is_protected_path("src/replayt_examples/foo.py")
    assert gate.is_protected_path("docs/RUN_LOG_SCHEMA.md")
    assert not gate.is_protected_path("tests/test_runner.py")
    assert not gate.is_protected_path("README.md")


def test_need_changelog_update() -> None:
    gate = _load_script()
    assert not gate.need_changelog_update(["tests/test_x.py", "README.md"])
    assert not gate.need_changelog_update(["src/replayt/foo.py", "CHANGELOG.md"])
    assert gate.need_changelog_update(["src/replayt/foo.py"])
    assert gate.need_changelog_update(["src/replayt_examples/x.py", "docs/foo.md"])


def test_main_fails_closed_when_git_diff_errors(monkeypatch) -> None:
    gate = _load_script()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    def boom(base_branch: str) -> list[str]:
        raise subprocess.CalledProcessError(2, ["git", "diff", "--name-only", f"origin/{base_branch}...HEAD"])

    monkeypatch.setattr(gate, "changed_files_vs_base", boom)
    assert gate.main() == 1


def test_changed_files_vs_base_marks_repo_as_safe_directory(tmp_path: Path, monkeypatch) -> None:
    gate = _load_script()
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        calls.append(cmd)
        stdout = "src/replayt/runner.py\n" if "diff" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    files = gate.changed_files_vs_base("main")

    assert files == ["src/replayt/runner.py"]
    expected_prefix = ["git", "-c", f"safe.directory={tmp_path.resolve()}"]
    assert calls[0][:3] == expected_prefix
    assert calls[1][:3] == expected_prefix
