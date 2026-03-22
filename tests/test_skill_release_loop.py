from __future__ import annotations

import datetime as dt
import importlib.util
import json
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


_ALL_DEFAULT_SKILLS = (
    "feat_staff_engineer",
    "feat_junior_onboarding",
    "feat_security_compliance",
    "feat_ml_llm_engineer",
    "feat_devops_sre",
    "feat_product_engineer",
    "feat_oss_maintainer",
    "feat_startup_ic",
    "feat_enterprise_integrator",
    "feat_framework_enthusiast",
    "feat_mcp_tooling",
    "feat_agent_harness_engineer",
    "review_design_fidelity",
    "improvedoc",
    "deslopdoc",
    "reviewcodebase",
)


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "origin.git"
    _git_no_cwd("init", "--bare", str(remote))

    for skill in _ALL_DEFAULT_SKILLS:
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


def test_codex_usage_limit_detection() -> None:
    mod = _load_script()
    assert mod.codex_usage_limit_log_detected("ERROR: You've hit your usage limit.")
    assert mod.codex_usage_limit_log_detected("usage limit exceeded")
    assert not mod.codex_usage_limit_log_detected("some other error")


def test_parse_try_again_at_local_same_calendar_day() -> None:
    mod = _load_script()
    tz = dt.timezone(dt.timedelta(hours=-5))
    now = dt.datetime(2026, 3, 21, 18, 0, tzinfo=tz)
    log = "ERROR: usage limit. try again at 7:05 PM."
    got = mod.parse_try_again_at_local(log, now=now)
    assert got == dt.datetime(2026, 3, 21, 19, 5, tzinfo=tz)


def test_parse_try_again_at_local_rolls_to_next_day() -> None:
    mod = _load_script()
    tz = dt.timezone.utc
    now = dt.datetime(2026, 3, 21, 20, 0, tzinfo=tz)
    log = "try again at 7:05 PM"
    got = mod.parse_try_again_at_local(log, now=now)
    assert got.date() == dt.date(2026, 3, 22)
    assert got.hour == 19 and got.minute == 5


def test_parse_try_again_at_local_24h_clock() -> None:
    mod = _load_script()
    tz = dt.timezone.utc
    now = dt.datetime(2026, 3, 21, 10, 0, tzinfo=tz)
    log = "try again at 19:05"
    got = mod.parse_try_again_at_local(log, now=now)
    assert got == dt.datetime(2026, 3, 21, 19, 5, tzinfo=tz)


def test_compute_usage_limit_delay_respects_max_wait() -> None:
    mod = _load_script()
    tz = dt.timezone.utc
    now = dt.datetime(2026, 3, 21, 12, 0, tzinfo=tz)
    resume = dt.datetime(2026, 3, 23, 12, 0, tzinfo=tz)
    assert mod.compute_usage_limit_delay(now, resume, buffer_seconds=0, max_wait_seconds=86400) is None


def test_compute_usage_limit_delay_includes_buffer() -> None:
    mod = _load_script()
    tz = dt.timezone.utc
    now = dt.datetime(2026, 3, 21, 12, 0, 0, tzinfo=tz)
    resume = dt.datetime(2026, 3, 21, 13, 0, 0, tzinfo=tz)
    d = mod.compute_usage_limit_delay(now, resume, buffer_seconds=60, max_wait_seconds=86400)
    assert d == 3600 + 60


def test_wait_on_codex_usage_limit_cli_flags() -> None:
    mod = _load_script()
    assert mod.parse_args([]).wait_on_codex_usage_limit is True
    assert mod.parse_args(["--no-wait-on-codex-usage-limit"]).wait_on_codex_usage_limit is False


def test_log_file_last_exit_code() -> None:
    mod = _load_script()
    assert mod.log_file_last_exit_code("foo\n### skill_release_loop: exit_code=1\n") == 1
    assert (
        mod.log_file_last_exit_code(
            "### skill_release_loop: exit_code=0\n### skill_release_loop: exit_code=1\n"
        )
        == 1
    )
    assert mod.log_file_last_exit_code("no footer") is None


def test_run_dir_is_resumable(tmp_path: Path) -> None:
    mod = _load_script()
    rd = tmp_path / "20260101-120000"
    rd.mkdir()
    skills = ["a", "b"]
    assert not mod.run_dir_is_resumable(rd, skills, 2, 1)
    (rd / "iter-01-a.log").write_text("x\n### skill_release_loop: exit_code=0\n", encoding="utf-8")
    assert mod.run_dir_is_resumable(rd, skills, 2, 1)
    (rd / "iter-01-b.log").write_text("y\n### skill_release_loop: exit_code=0\n", encoding="utf-8")
    (rd / "iter-01-check-01.log").write_text("z\n### skill_release_loop: exit_code=1\n", encoding="utf-8")
    assert mod.run_dir_is_resumable(rd, skills, 2, 1)
    (rd / "iter-01-check-01.log").write_text("z\n### skill_release_loop: exit_code=0\n", encoding="utf-8")
    assert not mod.run_dir_is_resumable(rd, skills, 2, 1)


def test_find_latest_resumable_run_dir(tmp_path: Path) -> None:
    mod = _load_script()
    root = tmp_path / "rel"
    root.mkdir()
    old = root / "20260101-100000"
    new = root / "20260102-100000"
    old.mkdir()
    new.mkdir()
    skills = ["s"]
    (old / "iter-01-s.log").write_text("### skill_release_loop: exit_code=1\n", encoding="utf-8")
    (new / "iter-01-s.log").write_text("### skill_release_loop: exit_code=1\n", encoding="utf-8")
    got = mod.find_latest_resumable_run_dir(root, skills, 3, 1)
    assert got == new


def test_resolve_run_directory_explicit(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "r"
    repo.mkdir()
    log_root = repo / ".replayt" / "skill-release"
    log_root.mkdir(parents=True)
    run_sub = log_root / "20260102-120000"
    run_sub.mkdir()
    monkeypatch.chdir(repo)
    args = mod.parse_args(["--resume", "20260102-120000"])
    args.checks = ["true"]
    skill_names = ["a"]
    got = mod.resolve_run_directory(repo, args, skill_names)
    assert got == run_sub.resolve()


def test_effective_allow_dirty_resume_implies_ok() -> None:
    mod = _load_script()
    assert mod.effective_allow_dirty(mod.parse_args([])) is False
    assert mod.effective_allow_dirty(mod.parse_args(["--allow-dirty"])) is True
    assert mod.effective_allow_dirty(mod.parse_args(["--resume", "20260101-120000"])) is True


def test_resolve_run_directory_auto_empty_raises(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".replayt" / "skill-release").mkdir(parents=True)
    monkeypatch.chdir(repo)
    args = mod.parse_args(["--resume"])
    args.checks = ["true"]
    with pytest.raises(mod.LoopError, match="No prior run directory"):
        mod.resolve_run_directory(repo, args, ["x"])


def test_find_latest_stamp_run_dir(tmp_path: Path) -> None:
    mod = _load_script()
    root = tmp_path / "rel"
    root.mkdir()
    empty_stamp = root / "20260101-100000"
    with_logs = root / "20260102-100000"
    newer = root / "20260103-100000"
    empty_stamp.mkdir()
    with_logs.mkdir()
    newer.mkdir()
    (with_logs / "iter-01-a.log").write_text("x\n", encoding="utf-8")
    (newer / "iter-01-a.log").write_text("y\n", encoding="utf-8")
    assert mod.find_latest_stamp_run_dir(root) == newer


def test_resolve_run_directory_auto_picks_newest_with_logs_even_when_iteration_complete(
    tmp_path: Path, monkeypatch
) -> None:
    mod = _load_script()
    repo = tmp_path / "r"
    repo.mkdir()
    log_root = repo / ".replayt" / "skill-release"
    log_root.mkdir(parents=True)
    older = log_root / "20260101-100000"
    newer = log_root / "20260102-100000"
    older.mkdir()
    newer.mkdir()
    skills = ["a", "b"]
    checks = 2
    for name in skills:
        (newer / f"iter-01-{name}.log").write_text(
            "ok\n### skill_release_loop: exit_code=0\n", encoding="utf-8"
        )
    for j in range(1, checks + 1):
        (newer / f"iter-01-check-{j:02d}.log").write_text(
            "ok\n### skill_release_loop: exit_code=0\n", encoding="utf-8"
        )
    (older / "iter-01-a.log").write_text(
        "fail\n### skill_release_loop: exit_code=1\n", encoding="utf-8"
    )

    monkeypatch.chdir(repo)
    args = mod.parse_args(["--resume"])
    args.checks = ["c1", "c2"]
    got = mod.resolve_run_directory(repo, args, skills)
    assert got == newer.resolve()


def test_dry_run_completes_without_worktree_changes(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    for skill in _ALL_DEFAULT_SKILLS:
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
    current = repo / ".replayt" / "skill-release" / "current.json"
    assert current.is_file()
    data = json.loads(current.read_text(encoding="utf-8"))
    assert data.get("outcome") == "dry_run_complete"
    assert data.get("active") is False
    assert data.get("max_iterations") == 1
    status_path = Path(data["run_dir"]) / "status.json"
    assert status_path.is_file()


def test_default_task_and_skill_command(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    args = mod.parse_args([])
    assert "feat_staff_engineer" in args.task
    assert args.skills == list(_ALL_DEFAULT_SKILLS)
    assert args.skill_command is None
    assert args.checks is None


def test_default_skill_command_passes_skill_root_placeholder(tmp_path: Path) -> None:
    mod = _load_script()
    command = mod.default_skill_command(tmp_path)
    assert "--skill-root {skill_root_q}" in command


def test_describe_skill_env_snippet_includes_skill_root() -> None:
    mod = _load_script()
    snippet = mod.describe_skill_env_snippet(
        {
            "REPO_ROOT": "repo",
            "SKILL_ROOT": "skills",
            "SKILL_NAME": "demo",
            "SKILL_ITERATION": "1",
            "SKILL_PROMPT_FILE": "prompt.md",
            "SKILL_LOG_FILE": "skill.log",
            "SKILL_TASK": "task",
        }
    )
    assert "SKILL_ROOT=skills" in snippet


def test_run_skill_iteration_exports_skill_root_and_placeholder(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    skill_root = repo / ".cursor" / "skills"
    _write(skill_root / "demo" / "SKILL.md", "# demo\n")
    run_dir = repo / ".replayt" / "skill-release"
    run_dir.mkdir(parents=True)
    args = mod.parse_args(["--skill-command", "echo {skill_root}"])
    captured: dict[str, object] = {}

    def fake_run_shell_command(command, repo_path, env, **kwargs):
        captured["command"] = command
        captured["repo"] = repo_path
        captured["env"] = env
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod, "run_shell_command", fake_run_shell_command)

    skill = mod.load_skill(skill_root, "demo")
    mod.run_skill_iteration(repo, [skill], args, run_dir, 1, None)

    assert captured["command"] == f"echo {skill_root.resolve()}"
    assert captured["repo"] == repo
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["SKILL_ROOT"] == str(skill_root.resolve())


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


def test_preflight_allows_dirty_when_resume_namespace(tmp_path: Path) -> None:
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
    args = mod.parse_args(["--resume", "20260101-120000"])
    mod.ensure_repo_preflight(repo, mod.effective_allow_dirty(args), dry_run=False)


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
            "--no-pre-tag-github-ci",
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
    expected_order = []
    for iteration in (1, 2):
        for skill in _ALL_DEFAULT_SKILLS:
            expected_order.append(f"{iteration}:{skill}")
        if iteration == 1:
            expected_order.extend(["1:fix_check", "1:fix_check", "1:fix_check"])
    assert order == expected_order

    assert _git(repo, "log", "-1", "--pretty=%s") == "release: v0.4.1"
    assert "v0.4.1" in _git(repo, "tag", "--list")

    cur = json.loads((repo / ".replayt" / "skill-release" / "current.json").read_text(encoding="utf-8"))
    assert cur["outcome"] == "released_local"
    assert cur["active"] is False
    assert cur["max_iterations"] == 3


def test_push_release_uses_explicit_branch_and_tag(monkeypatch) -> None:
    mod = _load_script()
    calls: list[list[str]] = []

    def fake_run_git(repo: Path, args: list[str], *, capture_output: bool = False):
        calls.append(args)
        return None

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    mod.push_release(Path("."), "origin", "main", "v1.2.3")
    assert calls == [
        ["push", "origin", "HEAD:refs/heads/main", "refs/tags/v1.2.3"],
    ]


def test_git_stdout_ignores_mis_set_git_dir(tmp_path: Path, monkeypatch) -> None:
    """Regression: inherited GIT_DIR must not make tags/commits target another repository."""
    mod = _load_script()
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    _git(repo_a, "init")
    _git(repo_b, "init")
    _git(repo_a, "branch", "-M", "main")
    _git(repo_b, "branch", "-M", "main")
    _git(repo_a, "config", "user.name", "Test User")
    _git(repo_a, "config", "user.email", "a@example.com")
    _git(repo_b, "config", "user.name", "Test User")
    _git(repo_b, "config", "user.email", "b@example.com")
    _write(repo_a / "f.txt", "a\n")
    _write(repo_b / "g.txt", "b\n")
    _git(repo_a, "add", ".")
    _git(repo_b, "add", ".")
    _git(repo_a, "commit", "-m", "a")
    _git(repo_b, "commit", "-m", "b")

    expected_head = mod.git_stdout(repo_a, ["rev-parse", "HEAD"]).strip()
    monkeypatch.setenv("GIT_DIR", str(repo_b / ".git"))
    assert mod.git_stdout(repo_a, ["rev-parse", "HEAD"]).strip() == expected_head


def test_run_git_marks_repo_safe_directory(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod.run_git(repo, ["status"], capture_output=True)

    assert captured["cmd"] == [
        "git",
        "-c",
        f"safe.directory={repo.resolve()}",
        "-C",
        str(repo.resolve()),
        "status",
    ]


def test_ensure_tag_absent_marks_repo_safe_directory(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod.ensure_tag_absent(repo, "v1.2.3")

    assert captured["cmd"] == [
        "git",
        "-c",
        f"safe.directory={repo.resolve()}",
        "-C",
        str(repo.resolve()),
        "rev-parse",
        "-q",
        "--verify",
        "refs/tags/v1.2.3",
    ]


def _minimal_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tag_repo"
    repo.mkdir()
    _write(repo / "f.txt", "x\n")
    _git(repo, "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_next_patch_version_without_local_tag_no_collision(tmp_path: Path) -> None:
    mod = _load_script()
    repo = _minimal_git_repo(tmp_path)
    assert mod.next_patch_version_without_local_tag(repo, "1.2.3") == "1.2.4"


def test_next_patch_version_without_local_tag_skips_existing(tmp_path: Path) -> None:
    mod = _load_script()
    repo = _minimal_git_repo(tmp_path)
    _git(repo, "tag", "-a", "v1.2.4", "-m", "v1.2.4")
    assert mod.next_patch_version_without_local_tag(repo, "1.2.3") == "1.2.5"


def test_next_patch_version_without_local_tag_max_collisions(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setattr(mod, "_MAX_LOCAL_TAG_COLLISION_SKIPS", 3)
    monkeypatch.setattr(mod, "tag_exists_locally", lambda _r, _t: True)
    with pytest.raises(mod.LoopError, match="Could not find an unused local"):
        mod.next_patch_version_without_local_tag(tmp_path / "noop", "1.0.0")


def test_run_shell_command_requires_stdout_pipe(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()

    class _FakeProc:
        stdout = None

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())

    with pytest.raises(mod.LoopError, match="stdout pipe was not captured"):
        mod.run_shell_command(
            "python -c \"print('x')\"",
            tmp_path,
            {},
            log_path=tmp_path / "cmd.log",
            stream_to_terminal=False,
        )
