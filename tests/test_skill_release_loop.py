from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest


def _load_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "skill_release_loop.py"
    spec = importlib.util.spec_from_file_location("skill_release_loop", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _git_no_cwd(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "origin.git"
    _git_no_cwd("init", "--bare", str(remote))

    for skill in ("createfeatures", "improvedoc", "deslopdoc", "reviewcodebase"):
        _write(repo / ".cursor" / "skills" / skill / "SKILL.md", f"# {skill}\n")

    _write(
        repo / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        ## 0.4.0 - 2026-03-21

        - Previous release note.
        """,
    )
    _write(
        repo / "pyproject.toml",
        """
        [build-system]
        requires = ["setuptools>=61", "wheel"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "replayt"
        version = "0.4.0"
        """,
    )
    _write(
        repo / "src" / "replayt" / "__init__.py",
        '__version__ = "0.4.0"\n',
    )
    _write(
        repo / "src" / "replayt" / "core.py",
        'VALUE = "base"\n',
    )
    _write(
        repo / "runner_backend.py",
        """
        from pathlib import Path
        import os

        repo = Path(os.environ["REPO_ROOT"])
        skill = os.environ["SKILL_NAME"]
        iteration = int(os.environ["SKILL_ITERATION"])

        trace = repo / ".replayt" / "skill-order.txt"
        trace.parent.mkdir(parents=True, exist_ok=True)
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(f"{iteration}:{skill}\\n")

        changelog = repo / "CHANGELOG.md"
        note = "- Automated release loop note.\\n"
        text = changelog.read_text(encoding="utf-8")
        marker = "## Unreleased\\n\\n"
        if note not in text:
            changelog.write_text(text.replace(marker, marker + note, 1), encoding="utf-8")

        core = repo / "src" / "replayt" / "core.py"
        tag = f"# {iteration}:{skill}\\n"
        current = core.read_text(encoding="utf-8")
        if tag not in current:
            core.write_text(current + tag, encoding="utf-8")

        if skill == "reviewcodebase" and iteration >= 2:
            ready = repo / ".replayt" / "tests-green"
            ready.write_text("ok\\n", encoding="utf-8")
        """,
    )
    _write(
        repo / "check_ready.py",
        """
        from pathlib import Path
        import sys

        ready = Path(".replayt/tests-green")
        raise SystemExit(0 if ready.exists() else 1)
        """,
    )

    _git(repo, "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, remote


def test_bump_patch_and_alias() -> None:
    mod = _load_script()
    assert mod.normalize_skill_name("createfeature") == "createfeatures"
    assert mod.bump_patch("1.2.3") == "1.2.4"


def test_dry_run_completes_without_worktree_changes(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    for skill in ("createfeatures", "improvedoc", "deslopdoc", "reviewcodebase"):
        _write(repo / ".cursor" / "skills" / skill / "SKILL.md", f"# {skill}\n")
    _write(
        repo / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        - Note.
        """,
    )
    _write(
        repo / "pyproject.toml",
        """
        [project]
        name = "x"
        version = "1.0.0"
        """,
    )
    _write(repo / "src" / "replayt" / "__init__.py", '__version__ = "1.0.0"\n')
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)
    rc = mod.main(
        [
            "--dry-run",
            "--skip-push",
            "--max-iterations",
            "1",
            "--check",
            "python -c \"raise SystemExit(0)\"",
        ]
    )
    assert rc == 0


def test_default_task_and_skill_command(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    args = mod.parse_args([])
    assert "createfeatures" in args.task
    assert args.skills == ["createfeatures", "improvedoc", "deslopdoc", "reviewcodebase"]
    assert args.skill_command is None
    assert args.checks is None


def test_preflight_rejects_dirty_worktree(tmp_path: Path) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "tracked.txt", "base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _write(repo / "tracked.txt", "dirty\n")
    with pytest.raises(mod.LoopError, match="not clean"):
        mod.ensure_repo_preflight(repo, allow_dirty=False, dry_run=False)


def test_preflight_allows_dirty_with_flag(tmp_path: Path) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "tracked.txt", "base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _write(repo / "tracked.txt", "dirty\n")
    mod.ensure_repo_preflight(repo, allow_dirty=True, dry_run=False)


def test_release_loop_runs_until_checks_pass_and_tags_release(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo, _remote = _init_repo(tmp_path)
    monkeypatch.chdir(repo)

    rc = mod.main(
        [
            "--task",
            "Tighten the repository and cut a patch release.",
            "--skill-command",
            "python runner_backend.py",
            "--check",
            "python check_ready.py",
            "--max-iterations",
            "3",
            "--skip-push",
        ]
    )

    assert rc == 0
    assert 'version = "0.4.1"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert '__version__ = "0.4.1"' in (repo / "src" / "replayt" / "__init__.py").read_text(encoding="utf-8")

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    today = date.today().isoformat()
    assert "## Unreleased\n\n## 0.4.1 - " + today in changelog
    assert "- Automated release loop note." in changelog

    order = (repo / ".replayt" / "skill-order.txt").read_text(encoding="utf-8").splitlines()
    assert order == [
        "1:createfeatures",
        "1:improvedoc",
        "1:deslopdoc",
        "1:reviewcodebase",
        "2:createfeatures",
        "2:improvedoc",
        "2:deslopdoc",
        "2:reviewcodebase",
    ]

    assert _git(repo, "log", "-1", "--pretty=%s") == "release: v0.4.1"
    assert "v0.4.1" in _git(repo, "tag", "--list")


def test_push_release_uses_explicit_branch_and_tag(monkeypatch) -> None:
    mod = _load_script()
    calls: list[list[str]] = []

    def fake_run_git(repo: Path, args: list[str], *, capture_output: bool = False):
        calls.append(args)
        return None

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    mod.push_release(Path("."), "origin", "main", "v1.2.3")
    assert calls == [
        ["push", "origin", "HEAD:refs/heads/main"],
        ["push", "origin", "refs/tags/v1.2.3"],
    ]
