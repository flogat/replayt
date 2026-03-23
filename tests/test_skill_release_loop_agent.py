from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest


def _load_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "skill_release_loop_agent.py"
    spec = importlib.util.spec_from_file_location("skill_release_loop_agent", path)
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


def test_unreleased_changelog_item_count(tmp_path: Path) -> None:
    mod = _load_script()
    repo = tmp_path / "r"
    repo.mkdir()
    cl = repo / "CHANGELOG.md"
    cl.write_text("# Log\n\n## Unreleased\n\n- A\n- B\n\n## 1.0\n", encoding="utf-8")
    assert mod.unreleased_changelog_item_count(repo) == 2
    cl.write_text("# Log\n\n## Unreleased\n\n\n## 1.0\n", encoding="utf-8")
    assert mod.unreleased_changelog_item_count(repo) == 0
    assert mod.unreleased_changelog_item_count(tmp_path / "no_repo") is None


def test_codex_usage_limit_detection() -> None:
    mod = _load_script()
    assert mod.codex_usage_limit_log_detected("ERROR: You've hit your usage limit.")
    assert mod.codex_usage_limit_log_detected("usage limit exceeded")
    assert not mod.codex_usage_limit_log_detected("some other error")


def test_skill_command_rel_placeholders_resolves_under_repo(tmp_path: Path) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = repo / "nested" / "p.md"
    prompt.parent.mkdir()
    prompt.write_text("x", encoding="utf-8")
    log_f = repo / "nested" / "l.log"
    log_f.write_text("", encoding="utf-8")
    inv = repo / "nested" / "i.invocation.json"
    inv.write_text("{}", encoding="utf-8")
    root = str(repo.resolve())
    rels = mod.skill_command_rel_placeholders(
        root,
        prompt_file=str(prompt.resolve()),
        log_file=str(log_f.resolve()),
        invocation_file=str(inv.resolve()),
        run_dir=str((repo / "nested").resolve()),
    )
    run_nested = (repo / "nested").resolve()
    assert (Path(root) / rels["prompt_rel"]).resolve() == prompt.resolve()
    assert (Path(root) / rels["log_rel"]).resolve() == log_f.resolve()
    assert (Path(root) / rels["invocation_rel"]).resolve() == inv.resolve()
    assert (Path(root) / rels["run_dir_rel"]).resolve() == run_nested


def test_fix_round_skill_command_context_includes_task_matching_env() -> None:
    """`{task}` must be defined for automated fix rounds (parity with SKILL_TASK / version JSON contract)."""

    mod = _load_script()
    base = {
        "skill_root": "/skills",
        "prompt_file": "/p.md",
        "log_file": "/l.log",
        "run_dir": "/run",
        "repo": "/repo",
        "iteration": "1",
        "max_iterations": "2",
        "step_index": "0",
        "step_total": "0",
        "pipeline_sha256": "aa",
        "skill_command_sha256": "bb",
        "task_sha256": "cc",
    }
    check_out = mod.render_command(
        "{task}",
        {
            **base,
            "skill": "fix_check",
            "skill_path": "fix_check",
            "task": mod.FIX_CHECK_TASK,
        },
    )
    assert check_out == mod.FIX_CHECK_TASK
    pre_out = mod.render_command(
        "{task}",
        {
            **base,
            "skill": "fix_pre_tag_ci",
            "skill_path": "fix_pre_tag_ci",
            "task": mod.FIX_PRE_TAG_CI_TASK,
        },
    )
    assert pre_out == mod.FIX_PRE_TAG_CI_TASK


def test_default_skill_command_uses_cursor_agent_prompt_placeholder(tmp_path: Path) -> None:
    mod = _load_script()
    command = mod.default_skill_command(tmp_path)
    assert "{prompt_file_q}" in command
    assert "composer-2" in command
    assert command.lstrip().startswith("agent ")


def test_skill_command_invokes_cursor_agent_cli() -> None:
    mod = _load_script()
    assert mod.skill_command_invokes_cursor_agent_cli('agent --model x -p "hi"')
    assert not mod.skill_command_invokes_cursor_agent_cli("python scripts/run_codex_skill.py")


def test_github_ci_verify_command_require_gh(tmp_path: Path) -> None:
    mod = _load_script()
    assert "--require-gh" in mod.github_ci_verify_command(tmp_path, require_gh=True)
    assert "--require-gh" not in mod.github_ci_verify_command(tmp_path, require_gh=False)


def test_parse_args_github_ci_verify_require_gh_flags() -> None:
    mod = _load_script()
    assert mod.parse_args([]).github_ci_verify_require_gh is True
    assert mod.parse_args(["--no-github-ci-verify-require-gh"]).github_ci_verify_require_gh is False
    assert mod.parse_args(["--github-ci-verify-require-gh"]).github_ci_verify_require_gh is True


def test_resolve_cursor_agent_executable_env_override(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    exe = tmp_path / "my-agent.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("REPLAYT_CURSOR_AGENT", str(exe))
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    assert mod.resolve_cursor_agent_executable() == str(exe.resolve())


def test_resolve_cursor_agent_executable_finds_local_bin(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    fake_home = tmp_path / "home"
    name = "agent.exe" if os.name == "nt" else "agent"
    agent_path = fake_home / ".local" / "bin" / name
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls, h=fake_home: h))
    monkeypatch.setattr(shutil, "which", lambda cmd, path=None: None)
    monkeypatch.delenv("REPLAYT_CURSOR_AGENT", raising=False)
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    got = mod.resolve_cursor_agent_executable()
    assert got == str(agent_path.resolve())


def test_augment_env_path_for_cursor_agent_prepends_bindir() -> None:
    mod = _load_script()
    bindir = Path("/opt/cursor/bin")
    agent_exe = bindir / "agent"
    args = argparse.Namespace(
        skill_command=mod.default_skill_command(Path(".")),
        cursor_agent_executable=str(agent_exe),
    )
    env = {"PATH": "/usr/bin:/bin"}
    mod.augment_env_path_for_cursor_agent(env, args)
    assert env["PATH"].startswith(str(bindir.resolve()) + os.pathsep)
    assert "/usr/bin" in env["PATH"]


def test_codex_usage_limit_detection_uses_latest_log_attempt_only() -> None:
    mod = _load_script()
    log = (
        "$ first\n\nERROR: usage limit. try again at 7:05 PM.\n### skill_release_loop: exit_code=1\n\n"
        "--- skill_release_loop: resume ---\n$ second\n\nDer Befehl \"agent\" wurde nicht gefunden.\n"
        "### skill_release_loop: exit_code=1\n"
    )
    assert mod.codex_usage_limit_log_detected(log)
    latest = mod.last_skill_attempt_output_for_usage_scan(log)
    assert not mod.codex_usage_limit_log_detected(latest)


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
    assert mod.parse_args([]).wait_on_codex_usage_limit is False
    assert mod.parse_args(["--wait-on-codex-usage-limit"]).wait_on_codex_usage_limit is True
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
    _real_which = shutil.which

    def fake_which(cmd: str, path: str | None = None) -> str | None:
        return "/fake/agent" if cmd == "agent" else _real_which(cmd, path=path)

    monkeypatch.setattr(shutil, "which", fake_which)
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


def test_main_preflight_fails_when_cursor_agent_not_on_path(tmp_path: Path, monkeypatch, capsys) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(mod, "resolve_cursor_agent_executable", lambda: None)
    rc = mod.main(["--dry-run", "--skip-push", "--max-iterations", "1", "--light"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "agent" in err.lower()
    assert "run_codex_skill" in err


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
    assert env["SKILL_RUN_DIR"] == str(run_dir.resolve())
    assert env["SKILL_RUN_STAMP"] == run_dir.name
    assert env["SKILL_STEP_INDEX"] == "1"
    assert env["SKILL_STEP_TOTAL"] == "1"
    expected_pipeline = mod.skill_pipeline_sha256(["demo"])
    assert env["SKILL_PIPELINE_SHA256"] == expected_pipeline
    cmd_template = "echo {skill_root}"
    expected_cmd_sha = mod.skill_command_template_sha256(cmd_template)
    assert env["SKILL_COMMAND_SHA256"] == expected_cmd_sha
    expected_task_sha = mod.skill_loop_task_sha256(args.task)
    assert env["SKILL_TASK_SHA256"] == expected_task_sha
    assert env["SKILL_PROMPT_REL"] == mod.path_under_repo_or_absolute(
        str(repo.resolve()), str((run_dir / "iter-01-demo.prompt.md").resolve())
    )
    inv_path = run_dir / "iter-01-demo.invocation.json"
    assert inv_path.is_file()
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    assert inv["schema"] == mod.SKILL_INVOCATION_SCHEMA
    assert inv["pipeline_sha256"] == expected_pipeline
    assert inv["skill_command_sha256"] == expected_cmd_sha
    assert inv["task_sha256"] == expected_task_sha
    assert inv["prompt_file_rel"] == env["SKILL_PROMPT_REL"]
    assert env["SKILL_INVOCATION_FILE"] == str(inv_path.resolve())
    assert env["SKILL_INVOCATION_REL"] == mod.path_under_repo_or_absolute(
        str(repo.resolve()), str(inv_path.resolve())
    )
    assert inv["log_file_rel"] == env["SKILL_LOG_REL"]
    assert inv["run_dir_rel"] == env["SKILL_RUN_DIR_REL"]
    assert inv["skill_name"] == "demo"
    assert inv["skill_requested_name"] == "demo"
    assert inv["iteration"] == 1
    assert inv["max_iterations"] == mod.parse_args([]).max_iterations
    assert inv["step_index"] == 1
    assert inv["step_total"] == 1
    assert inv["repo_root"] == str(repo.resolve())
    assert inv["run_dir"] == str(run_dir.resolve())
    assert inv["run_stamp"] == run_dir.name
    assert inv["injected_env_keys"] == sorted(mod.SKILL_LOOP_MAIN_INJECTED_ENV_KEYS)
    assert inv["prompt_file"] == str((run_dir / "iter-01-demo.prompt.md").resolve())
    assert inv["log_file"] == str((run_dir / "iter-01-demo.log").resolve())
    assert "Pipeline step: 1/1" in (run_dir / "iter-01-demo.prompt.md").read_text(encoding="utf-8")
    pipe_path = run_dir / "pipeline.json"
    assert pipe_path.is_file()
    pipe = json.loads(pipe_path.read_text(encoding="utf-8"))
    assert pipe["schema"] == mod.SKILL_RELEASE_PIPELINE_SCHEMA
    assert pipe["skills"] == ["demo"]
    assert pipe["pipeline_sha256"] == expected_pipeline
    assert pipe["skill_command_sha256"] == expected_cmd_sha
    assert pipe["task_sha256"] == expected_task_sha
    assert pipe["run_stamp"] == run_dir.name


def test_skill_pipeline_file_rejects_reordered_skills_on_resume(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "task", "backend-a")
    with pytest.raises(mod.LoopError, match="same --skills"):
        mod.ensure_skill_release_pipeline_file(run_dir, ["b", "a"], "task", "backend-a")


def test_skill_pipeline_file_rejects_skill_command_change_on_resume(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "task", "backend-a")
    with pytest.raises(mod.LoopError, match="skill_command_sha256"):
        mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "task", "backend-b")


def test_skill_pipeline_file_rejects_task_change_on_resume(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "first task", "backend-a")
    with pytest.raises(mod.LoopError, match="task_sha256"):
        mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "second task", "backend-a")


def test_skill_pipeline_resume_ignores_missing_task_sha256(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sha = mod.skill_pipeline_sha256(["a", "b"])
    cmd_sha = mod.skill_command_template_sha256("backend-a")
    (run_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "schema": mod.SKILL_RELEASE_PIPELINE_SCHEMA,
                "skills": ["a", "b"],
                "pipeline_sha256": sha,
                "skill_command_sha256": cmd_sha,
                "task": "legacy",
                "written_at": "2026-01-01T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "new task", "backend-a") == sha


def test_skill_pipeline_resume_ignores_missing_skill_command_sha256(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sha = mod.skill_pipeline_sha256(["a", "b"])
    (run_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "schema": mod.SKILL_RELEASE_PIPELINE_SCHEMA,
                "skills": ["a", "b"],
                "pipeline_sha256": sha,
                "task": "legacy",
                "written_at": "2026-01-01T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert mod.ensure_skill_release_pipeline_file(run_dir, ["a", "b"], "task", "new-backend") == sha


def test_load_skill_release_pipeline_sha256_roundtrip(tmp_path: Path) -> None:
    mod = _load_script()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sha = mod.ensure_skill_release_pipeline_file(run_dir, ["x"], "t", "")
    assert mod.load_skill_release_pipeline_sha256(run_dir) == sha


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
        ["push", "origin", "HEAD:refs/heads/main"],
        ["push", "origin", "refs/tags/v1.2.3"],
    ]


def _pre_tag_fix_args(mod, repo: Path, *, max_fix: int) -> argparse.Namespace:
    return argparse.Namespace(
        pre_tag_github_ci_max_fix_attempts=max_fix,
        quiet=True,
        skill_command=mod.default_skill_command(repo),
        skill_root=".cursor/skills",
        max_iterations=3,
        status_interval=0.0,
        task="pre-tag unit test",
    )


def _stub_pipeline_json_for_pre_tag(mod, repo: Path, run_dir: Path) -> None:
    mod.ensure_skill_release_pipeline_file(
        run_dir, ["pre_tag_ci_stub"], "pre-tag unit test", mod.default_skill_command(repo)
    )


def test_run_pre_tag_github_ci_with_fixes_zero_max_fails_fast(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _stub_pipeline_json_for_pre_tag(mod, repo, run_dir)
    pre_tag_log = run_dir / "pre-tag-iter-01-github-ci.log"
    pre_tag_log.write_text("fail\n", encoding="utf-8")
    args = _pre_tag_fix_args(mod, repo, max_fix=0)

    def fake_run_shell(command, r, env, *, log_path=None, **kwargs):
        if log_path and log_path.name.endswith("github-ci.log") and "fix" not in log_path.name:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod, "run_shell_command", fake_run_shell)
    with pytest.raises(mod.LoopError, match="Pre-tag GitHub Actions verification failed \\(exit 1\\)"):
        mod.run_pre_tag_github_ci_with_fixes(
            repo, args, run_dir, 1, None, "verify-cmd", pre_tag_log, {}
        )


def test_run_pre_tag_github_ci_with_fixes_retries_after_fix(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _stub_pipeline_json_for_pre_tag(mod, repo, run_dir)
    pre_tag_log = run_dir / "pre-tag-iter-01-github-ci.log"
    args = _pre_tag_fix_args(mod, repo, max_fix=3)
    shell_calls: list[tuple[str | None, str]] = []

    def fake_run_shell(command, r, env, *, log_path=None, **kwargs):
        lp = str(log_path) if log_path else None
        shell_calls.append((lp, command))
        if log_path and log_path.name.endswith("github-ci.log") and "fix" not in log_path.name:
            n = sum(
                1
                for lp2, _ in shell_calls
                if lp2
                and Path(lp2).name.endswith("github-ci.log")
                and "fix" not in Path(lp2).name
            )
            return subprocess.CompletedProcess(command, 0 if n >= 2 else 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod, "run_shell_command", fake_run_shell)
    monkeypatch.setattr(mod, "git_changed_files", lambda _r: ["patched.txt"])
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "", ""),
    )

    mod.run_pre_tag_github_ci_with_fixes(repo, args, run_dir, 1, None, "verify-cmd", pre_tag_log, {})
    verify_calls = sum(
        1
        for lp, _ in shell_calls
        if lp and Path(lp).name.endswith("github-ci.log") and "fix" not in Path(lp).name
    )
    assert verify_calls == 2
    assert any(lp and "github-ci-fix" in lp for lp, _ in shell_calls)


def test_run_pre_tag_github_ci_with_fixes_exhausts_max_rounds(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _stub_pipeline_json_for_pre_tag(mod, repo, run_dir)
    pre_tag_log = run_dir / "pre-tag-iter-01-github-ci.log"
    pre_tag_log.write_text("x\n", encoding="utf-8")
    args = _pre_tag_fix_args(mod, repo, max_fix=1)

    def fake_run_shell(command, r, env, *, log_path=None, **kwargs):
        if log_path and log_path.name.endswith("github-ci.log") and "fix" not in log_path.name:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod, "run_shell_command", fake_run_shell)
    monkeypatch.setattr(mod, "git_changed_files", lambda _r: ["patched.txt"])
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "", ""),
    )

    with pytest.raises(mod.LoopError, match="after 1 fix round"):
        mod.run_pre_tag_github_ci_with_fixes(
            repo, args, run_dir, 1, None, "verify-cmd", pre_tag_log, {}
        )


def test_run_pre_tag_github_ci_with_fixes_no_working_tree_change_raises(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _stub_pipeline_json_for_pre_tag(mod, repo, run_dir)
    pre_tag_log = run_dir / "pre-tag-iter-01-github-ci.log"
    pre_tag_log.write_text("x\n", encoding="utf-8")
    args = _pre_tag_fix_args(mod, repo, max_fix=3)

    def fake_run_shell(command, r, env, *, log_path=None, **kwargs):
        if log_path and log_path.name.endswith("github-ci.log") and "fix" not in log_path.name:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod, "run_shell_command", fake_run_shell)
    monkeypatch.setattr(mod, "git_changed_files", lambda _r: [])

    with pytest.raises(mod.LoopError, match="no working tree changes"):
        mod.run_pre_tag_github_ci_with_fixes(
            repo, args, run_dir, 1, None, "verify-cmd", pre_tag_log, {}
        )


def test_parse_args_pre_tag_github_ci_max_fix_attempts_invalid() -> None:
    mod = _load_script()
    with pytest.raises(SystemExit):
        mod.parse_args(["--pre-tag-github-ci-max-fix-attempts", "-1"])


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
    assert captured["kwargs"].get("stdin") is subprocess.DEVNULL


def test_ensure_tag_absent_marks_repo_safe_directory(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    repo = tmp_path / "repo"
    repo.mkdir()
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
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
    assert captured["kwargs"].get("stdin") is subprocess.DEVNULL


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
