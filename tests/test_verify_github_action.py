from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _load_verify_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "verify_github_action.py"
    spec = importlib.util.spec_from_file_location("verify_github_action_testmod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_resolve_gh_replayt_gh_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLAYT_GH", raising=False)
    monkeypatch.delenv("GH_EXE", raising=False)
    exe = tmp_path / "gh"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("REPLAYT_GH", str(exe))
    monkeypatch.setattr(shutil, "which", lambda _: None)

    mod = _load_verify_script()
    assert mod.resolve_gh_executable() == str(exe.resolve())


def test_resolve_gh_replayt_gh_overrides_which(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_gh = tmp_path / "from_env"
    env_gh.write_text("", encoding="utf-8")
    which_gh = tmp_path / "from_which"
    which_gh.write_text("", encoding="utf-8")
    monkeypatch.setenv("REPLAYT_GH", str(env_gh))
    monkeypatch.setattr(shutil, "which", lambda name: str(which_gh) if name == "gh" else None)

    mod = _load_verify_script()
    assert mod.resolve_gh_executable() == str(env_gh.resolve())


def test_resolve_gh_uses_shutil_which(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLAYT_GH", raising=False)
    monkeypatch.delenv("GH_EXE", raising=False)
    which_gh = tmp_path / "from_which"
    which_gh.write_text("", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: str(which_gh) if name == "gh" else None)

    mod = _load_verify_script()
    assert mod.resolve_gh_executable() == str(which_gh)


@pytest.mark.skipif(os.name != "nt", reason="Probes Windows GitHub CLI install layout")
def test_resolve_gh_windows_program_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("REPLAYT_GH", raising=False)
    monkeypatch.delenv("GH_EXE", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    empty_x86 = tmp_path / "empty_x86"
    empty_x86.mkdir()
    monkeypatch.setenv("ProgramFiles(x86)", str(empty_x86))
    local = tmp_path / "localappdata"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    gh = tmp_path / "GitHub CLI" / "gh.exe"
    gh.parent.mkdir(parents=True)
    gh.write_text("", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _: None)

    mod = _load_verify_script()
    assert mod.resolve_gh_executable() == str(gh.resolve())
    err = capsys.readouterr().err
    assert "outside PATH" in err


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_resolve_git_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    mod = _load_verify_script()
    assert mod.resolve_git_repo_root() == tmp_path.resolve()


def test_resolve_git_repo_root_not_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    mod = _load_verify_script()
    with pytest.raises(RuntimeError, match="Not a git repository"):
        mod.resolve_git_repo_root()
