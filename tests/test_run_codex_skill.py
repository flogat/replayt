from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "run_codex_skill.py"
    spec = importlib.util.spec_from_file_location("run_codex_skill", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_resolve_skill_root_uses_repo_default(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    skill_root = repo / ".cursor" / "skills"
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(mod, "repo_root", lambda: repo)

    assert mod.resolve_skill_root(None) == skill_root.resolve()


def test_resolve_skill_root_prefers_cli_flag_over_env(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    env_root = repo / ".cursor" / "skills"
    env_root.mkdir(parents=True)
    explicit_root = tmp_path / "alt-skills"
    explicit_root.mkdir()
    monkeypatch.setattr(mod, "repo_root", lambda: repo)
    monkeypatch.setenv("SKILL_ROOT", str(env_root))

    assert mod.resolve_skill_root(str(explicit_root)) == explicit_root.resolve()


def test_resolve_skill_root_rejects_missing_or_non_directory(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = tmp_path / "skill-root.txt"
    file_path.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(mod, "repo_root", lambda: repo)

    with pytest.raises(FileNotFoundError, match="Skill root not found"):
        mod.resolve_skill_root(str(tmp_path / "missing"))
    with pytest.raises(NotADirectoryError, match="Skill root is not a directory"):
        mod.resolve_skill_root(str(file_path))


def test_main_invokes_codex_exec_without_skill_root_flag(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    skill_root = repo / ".cursor" / "skills"
    skill_root.mkdir(parents=True)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("follow the prompt", encoding="utf-8")
    binary = tmp_path / "codex.exe"
    captured: dict[str, object] = {}

    monkeypatch.setattr(mod, "repo_root", lambda: repo)
    monkeypatch.setattr(mod, "ensure_codex_installed", lambda: binary)
    monkeypatch.setattr(mod, "codex_path_entries", lambda _binary: [])

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    rc = mod.main(["--prompt-file", str(prompt)])

    assert rc == 0
    assert captured["cmd"] == [
        str(binary),
        "exec",
        "-C",
        str(repo),
        "--skip-git-repo-check",
        "--full-auto",
        "-",
    ]
    assert "--skill-root" not in captured["cmd"]
    kwargs = captured["kwargs"]
    assert kwargs["cwd"] == repo
    assert kwargs["input"] == b"follow the prompt"


def test_main_add_dir_when_skill_root_outside_repo(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "external-skills"
    outside.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x\n", encoding="utf-8")
    binary = tmp_path / "codex.exe"
    captured: dict[str, object] = {}

    monkeypatch.setattr(mod, "repo_root", lambda: repo)
    monkeypatch.setattr(mod, "ensure_codex_installed", lambda: binary)
    monkeypatch.setattr(mod, "codex_path_entries", lambda _binary: [])

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    rc = mod.main(["--prompt-file", str(prompt), "--skill-root", str(outside)])
    assert rc == 0
    cmd = captured["cmd"]
    assert "--add-dir" in cmd
    assert str(outside.resolve()) in cmd
    assert "--skill-root" not in cmd
