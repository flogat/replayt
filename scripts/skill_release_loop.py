#!/usr/bin/env python3
"""Run repository skills in a loop, then cut a patch release when checks pass."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Ralph-style pipeline: ideation → review → remediation → doc tone (docs last, after code settles).
DEFAULT_SKILLS = ("createfeatures", "improvedoc", "deslopdoc", "reviewcodebase")
DEFAULT_TASK = (
    "Run the repository skill loop in this order: createfeatures (new feature ideas), improvedoc "
    "(docs and repo improvements), deslopdoc (de-AI / humanize documentation), reviewcodebase "
    "(review plus apply fixes in-repo). Apply changes directly in the working tree, keep CHANGELOG.md "
    "updated under Unreleased, and leave the workspace ready for the outer release loop to bump "
    "the patch version, create the tag, and push once all checks pass."
)
SKILL_ALIASES = {"createfeature": "createfeatures"}
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
UNRELEASED_RE = re.compile(r"(?ms)^## Unreleased\s*$\n(?P<body>.*?)(?=^##\s|\Z)")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class LoopError(RuntimeError):
    """Raised when the release loop cannot proceed safely."""


@dataclass(frozen=True)
class SkillSpec:
    requested_name: str
    name: str
    path: Path
    instructions: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the repository's skill prompts in order until checks pass, then bump the patch version, "
            "tag, and push."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The script is backend-agnostic. --skill-command runs once per skill and can use placeholders:\n"
            "  {skill} {skill_path} {prompt_file} {log_file} {repo} {iteration} {max_iterations}\n"
            "Quoted variants are also available via *_q (for example {prompt_file_q}).\n"
            "The same values are exported as environment variables prefixed with SKILL_ plus REPO_ROOT.\n"
            "Progress: prints configuration, a decision-tree summary, each command and log path, streamed "
            "child output (unless --quiet), and explicit decision lines after checks. Use --quiet for logs only."
        ),
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Shared task/instruction appended to every skill prompt.",
    )
    parser.add_argument(
        "--skill-command",
        help="Shell command used to execute one skill prompt. Runs once per skill in each iteration.",
    )
    parser.add_argument(
        "--skill-root",
        default=".cursor/skills",
        help="Directory that contains the repository skill folders (default: .cursor/skills).",
    )
    parser.add_argument(
        "--skill",
        dest="skills",
        action="append",
        help="Skill folder name to run. Repeat to override the default sequence.",
    )
    parser.add_argument(
        "--check",
        dest="checks",
        action="append",
        help="Shell command used for validation after each full skill cycle. Repeatable.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum number of full skill cycles before failing (default: 3).",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Remote used for the final push (default: origin).",
    )
    parser.add_argument(
        "--branch",
        help="Remote branch to push. Defaults to the current branch.",
    )
    parser.add_argument(
        "--commit-message",
        default="release: v{version}",
        help="Commit message template used for the release commit (default: release: v{version}).",
    )
    parser.add_argument(
        "--log-dir",
        default=".replayt/skill-release",
        help="Directory used for generated prompts and command logs (default: .replayt/skill-release).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Skip the clean-worktree preflight. Unsafe for normal releases.",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Create the release commit and tag locally but do not push them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands without executing them.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not stream child-process output to the terminal (logs are still written).",
    )
    args = parser.parse_args(argv)
    if args.max_iterations < 1:
        parser.error("--max-iterations must be >= 1")
    if args.skills is None:
        args.skills = list(DEFAULT_SKILLS)
    return args


def quote_for_shell(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def normalize_skill_name(name: str) -> str:
    return SKILL_ALIASES.get(name, name)


def repo_python(repo: Path) -> Path:
    candidates = []
    if os.name == "nt":
        candidates.append(repo / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(repo / ".venv" / "bin" / "python")
    candidates.append(Path(sys.executable).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise LoopError("Could not find a Python executable for default commands")


def repo_ruff(repo: Path) -> str:
    candidates = []
    if os.name == "nt":
        candidates.append(repo / ".venv" / "Scripts" / "ruff.exe")
    else:
        candidates.append(repo / ".venv" / "bin" / "ruff")
    for candidate in candidates:
        if candidate.exists():
            return quote_for_shell(str(candidate))
    return "ruff"


def default_skill_command(repo: Path) -> str:
    python_exe = quote_for_shell(str(repo_python(repo)))
    runner = quote_for_shell(str(repo / "scripts" / "run_codex_skill.py"))
    return f"{python_exe} {runner} --prompt-file {{prompt_file_q}}"


def default_check_commands(repo: Path) -> list[str]:
    python_exe = quote_for_shell(str(repo_python(repo)))
    ruff_exe = repo_ruff(repo)
    return [
        f"{ruff_exe} check src tests scripts",
        f"{python_exe} -m pytest",
    ]


def load_skill(skill_root: Path, name: str) -> SkillSpec:
    resolved_name = normalize_skill_name(name)
    skill_path = skill_root / resolved_name / "SKILL.md"
    if not skill_path.exists():
        raise LoopError(f"Skill '{name}' was not found at {skill_path}")
    return SkillSpec(
        requested_name=name,
        name=resolved_name,
        path=skill_path,
        instructions=skill_path.read_text(encoding="utf-8"),
    )


def build_prompt(skill: SkillSpec, task: str, repo: Path, iteration: int, max_iterations: int) -> str:
    return (
        f"Repository root: {repo}\n"
        f"Skill: {skill.name}\n"
        f"Requested as: {skill.requested_name}\n"
        f"Iteration: {iteration}/{max_iterations}\n\n"
        "Follow the skill instructions below exactly.\n"
        "Apply repository changes directly in the working tree.\n"
        "Do not commit, tag, or push; the outer release loop owns that.\n"
        "Keep CHANGELOG.md updated under Unreleased for the changes you make.\n\n"
        "Shared task for this loop:\n"
        f"{task}\n\n"
        "=== SKILL FILE START ===\n"
        f"{skill.instructions}\n"
        "=== SKILL FILE END ===\n"
    )


def ensure_repo_preflight(repo: Path, allow_dirty: bool, dry_run: bool) -> None:
    require_git_repo(repo)
    if dry_run or allow_dirty:
        return
    status = git_stdout(repo, ["status", "--porcelain"]).strip()
    if status:
        raise LoopError(
            "Working tree is not clean; commit or stash changes before running the release loop, "
            "or pass --allow-dirty."
        )


def require_git_repo(repo: Path) -> None:
    run_git(repo, ["rev-parse", "--show-toplevel"], capture_output=True)


def render_command(template: str, context: dict[str, str]) -> str:
    render_values = dict(context)
    for key, value in context.items():
        render_values[f"{key}_q"] = quote_for_shell(value)
    try:
        return template.format_map(render_values)
    except KeyError as exc:
        raise LoopError(f"Unknown placeholder in command template: {exc.args[0]}") from exc


def progress_line(message: str, *, dest: TextIO = sys.stdout, end: str = "\n") -> None:
    print(message, file=dest, end=end, flush=True)


def progress_banner(title: str, *, dest: TextIO = sys.stdout) -> None:
    progress_line("", dest=dest)
    progress_line(f"=== {title} ===", dest=dest)


def describe_skill_env_snippet(env: dict[str, str], *, task_max: int = 160) -> str:
    keys = (
        "REPO_ROOT",
        "SKILL_NAME",
        "SKILL_ITERATION",
        "SKILL_PROMPT_FILE",
        "SKILL_LOG_FILE",
    )
    lines = [f"{k}={env.get(k, '')}" for k in keys]
    task = env.get("SKILL_TASK", "")
    if len(task) > task_max:
        task = task[: task_max - 3] + "..."
    lines.append(f"SKILL_TASK={task}")
    return "\n".join(lines)


def run_shell_command(
    command: str,
    repo: Path,
    env: dict[str, str],
    *,
    log_path: Path | None = None,
    dry_run: bool = False,
    stream_to_terminal: bool = True,
    progress_label: str = "",
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    if dry_run:
        label = f"{progress_label} " if progress_label else ""
        progress_line(f"[dry-run] {label}{command}")
        return subprocess.CompletedProcess(command, 0, "", "")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = f"[{progress_label}] " if progress_label else ""
        progress_line(f"{prefix}Command: {command}")
        progress_line(f"{prefix}Log file: {log_path}")
        if progress_label.startswith("skill:"):
            progress_line(f"{prefix}Environment (subset):")
            for line in describe_skill_env_snippet(env).splitlines():
                progress_line(f"{prefix}{line}")

        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"$ {command}\n\n")
            proc = subprocess.Popen(
                command,
                cwd=repo,
                env=env,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                handle.write(line)
                if stream_to_terminal:
                    progress_line(f"{prefix}{line}", end="")
            return_code = proc.wait()

        if return_code != 0:
            progress_line(f"{prefix}Exit code: {return_code} (failure)")
            if expect_success:
                raise LoopError(
                    f"Command failed with exit code {return_code}: {command}\nSee {log_path}"
                )
        else:
            progress_line(f"{prefix}Exit code: 0 (success)")
        return subprocess.CompletedProcess(command, return_code, "", "")

    result = subprocess.run(command, cwd=repo, env=env, shell=True, text=True)
    if result.returncode != 0:
        if expect_success:
            raise LoopError(f"Command failed with exit code {result.returncode}: {command}")
    return result


def run_skill_iteration(
    repo: Path,
    skills: list[SkillSpec],
    args: argparse.Namespace,
    run_dir: Path,
    iteration: int,
) -> None:
    progress_banner(f"Iteration {iteration}/{args.max_iterations}: skills")
    progress_line(
        "Decision: run each skill in sequence; each step invokes --skill-command with a fresh prompt file."
    )
    for skill in skills:
        stem = f"iter-{iteration:02d}-{skill.name}"
        prompt_path = run_dir / f"{stem}.prompt.md"
        log_path = run_dir / f"{stem}.log"
        prompt_path.write_text(build_prompt(skill, args.task, repo, iteration, args.max_iterations), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "REPO_ROOT": str(repo),
                "SKILL_NAME": skill.name,
                "SKILL_REQUESTED_NAME": skill.requested_name,
                "SKILL_PATH": str(skill.path),
                "SKILL_PROMPT_FILE": str(prompt_path),
                "SKILL_LOG_FILE": str(log_path),
                "SKILL_ITERATION": str(iteration),
                "SKILL_MAX_ITERATIONS": str(args.max_iterations),
                "SKILL_TASK": args.task,
            }
        )
        command = render_command(
            args.skill_command,
            {
                "skill": skill.name,
                "skill_path": str(skill.path),
                "prompt_file": str(prompt_path),
                "log_file": str(log_path),
                "repo": str(repo),
                "iteration": str(iteration),
                "max_iterations": str(args.max_iterations),
                "task": args.task,
            },
        )
        progress_banner(f"Skill: {skill.name}")
        progress_line(f"Prompt written: {prompt_path}")
        progress_line(f"Skill definition: {skill.path}")
        run_shell_command(
            command,
            repo,
            env,
            log_path=log_path,
            dry_run=args.dry_run,
            stream_to_terminal=not args.quiet,
            progress_label=f"skill:{skill.name}",
        )


def run_checks(repo: Path, args: argparse.Namespace, run_dir: Path, iteration: int) -> bool:
    progress_banner(f"Iteration {iteration}/{args.max_iterations}: checks")
    progress_line(
        f"Decision: run {len(args.checks)} check command(s) in order; all must exit 0 to finish the loop "
        "successfully."
    )
    for index, template in enumerate(args.checks, start=1):
        log_path = run_dir / f"iter-{iteration:02d}-check-{index:02d}.log"
        env = os.environ.copy()
        env["REPO_ROOT"] = str(repo)
        command = render_command(template, {"repo": str(repo), "iteration": str(iteration)})
        progress_banner(f"Check {index}/{len(args.checks)}")
        if args.dry_run:
            run_shell_command(
                command,
                repo,
                env,
                log_path=log_path,
                dry_run=True,
                progress_label=f"check:{iteration:02d}-{index:02d}",
            )
            progress_line("Decision: dry-run assumes this check would pass.")
            continue
        completed = run_shell_command(
            command,
            repo,
            env,
            log_path=log_path,
            stream_to_terminal=not args.quiet,
            progress_label=f"check:{iteration:02d}-{index:02d}",
            expect_success=False,
        )
        if completed.returncode != 0:
            progress_line(
                f"Decision: check {index}/{len(args.checks)} failed (exit {completed.returncode}) -> "
                "stop this iteration without releasing."
            )
            if iteration < args.max_iterations:
                progress_line(f"Next: start iteration {iteration + 1} (skills run again from the top).")
            else:
                progress_line("Next: no further iterations allowed (--max-iterations exhausted).")
            progress_line(f"Full output: {log_path}")
            return False
        progress_line(f"Decision: check {index}/{len(args.checks)} passed -> continue.")
    progress_line(
        f"Decision: all checks passed on iteration {iteration} -> exit skill/check loop "
        "(proceed to dry-run summary or release gates)."
    )
    return True


def git_stdout(repo: Path, args: list[str]) -> str:
    completed = run_git(repo, args, capture_output=True)
    return completed.stdout


def run_git(repo: Path, args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() if capture_output and completed.stderr else "git command failed"
        raise LoopError(f"git {' '.join(args)} failed: {detail}")
    return completed


def git_changed_files(repo: Path) -> list[str]:
    tracked = git_stdout(repo, ["diff", "--name-only", "HEAD", "--"]).splitlines()
    untracked = git_stdout(repo, ["ls-files", "--others", "--exclude-standard"]).splitlines()
    files = {path.strip() for path in tracked + untracked if path.strip()}
    return sorted(files)


def parse_version_from_text(text: str, pattern: re.Pattern[str], label: str) -> tuple[str, re.Match[str]]:
    match = pattern.search(text)
    if not match:
        raise LoopError(f"Could not find {label} version string")
    version = match.group(1)
    if not SEMVER_RE.fullmatch(version):
        raise LoopError(f"{label} version is not major.minor.patch: {version}")
    return version, match


def current_version(repo: Path) -> str:
    pyproject_text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    init_text = (repo / "src" / "replayt" / "__init__.py").read_text(encoding="utf-8")
    pyproject_version, _ = parse_version_from_text(pyproject_text, PYPROJECT_VERSION_RE, "pyproject.toml")
    init_version, _ = parse_version_from_text(init_text, INIT_VERSION_RE, "src/replayt/__init__.py")
    if pyproject_version != init_version:
        raise LoopError(
            "pyproject.toml and src/replayt/__init__.py disagree on the current version: "
            f"{pyproject_version} != {init_version}"
        )
    return pyproject_version


def bump_patch(version: str) -> str:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise LoopError(f"Version is not major.minor.patch: {version}")
    major, minor, patch = match.groups()
    return f"{major}.{minor}.{int(patch) + 1}"


def replace_version(repo: Path, new_version: str) -> None:
    pyproject_path = repo / "pyproject.toml"
    init_path = repo / "src" / "replayt" / "__init__.py"
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    init_text = init_path.read_text(encoding="utf-8")
    _, pyproject_match = parse_version_from_text(pyproject_text, PYPROJECT_VERSION_RE, "pyproject.toml")
    _, init_match = parse_version_from_text(init_text, INIT_VERSION_RE, "src/replayt/__init__.py")
    pyproject_path.write_text(
        pyproject_text[: pyproject_match.start(1)] + new_version + pyproject_text[pyproject_match.end(1) :],
        encoding="utf-8",
    )
    init_path.write_text(
        init_text[: init_match.start(1)] + new_version + init_text[init_match.end(1) :],
        encoding="utf-8",
    )


def finalize_changelog(repo: Path, new_version: str, today: dt.date) -> None:
    changelog_path = repo / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(new_version)}(?:\s|$)", changelog_text, re.MULTILINE):
        raise LoopError(f"CHANGELOG.md already has a section for {new_version}")
    match = UNRELEASED_RE.search(changelog_text)
    if not match:
        raise LoopError("CHANGELOG.md must contain a '## Unreleased' section")
    unreleased_body = match.group("body").strip()
    if not unreleased_body:
        raise LoopError("CHANGELOG.md has an empty Unreleased section")
    replacement = f"## Unreleased\n\n## {new_version} - {today.isoformat()}\n\n{unreleased_body}\n\n"
    updated = changelog_text[: match.start()] + replacement + changelog_text[match.end() :].lstrip("\n")
    changelog_path.write_text(updated, encoding="utf-8")


def current_branch(repo: Path) -> str:
    branch = git_stdout(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch == "HEAD":
        raise LoopError("Detached HEAD is not supported for the release push")
    return branch


def ensure_remote(repo: Path, remote: str) -> None:
    run_git(repo, ["remote", "get-url", remote], capture_output=True)


def ensure_tag_absent(repo: Path, tag_name: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        raise LoopError(f"Tag {tag_name} already exists")


def create_release_commit(repo: Path, new_version: str, commit_message_template: str) -> None:
    commit_message = commit_message_template.format(version=new_version)
    run_git(repo, ["add", "-A"])
    run_git(repo, ["commit", "-m", commit_message])


def create_tag(repo: Path, tag_name: str) -> None:
    run_git(repo, ["tag", "-a", tag_name, "-m", tag_name])


def push_release(repo: Path, remote: str, branch: str, tag_name: str) -> None:
    run_git(repo, ["push", remote, f"HEAD:refs/heads/{branch}"])
    run_git(repo, ["push", remote, f"refs/tags/{tag_name}"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path.cwd().resolve()
    skill_root = (repo / args.skill_root).resolve()
    run_dir = (repo / args.log_dir / dt.datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    if args.skill_command is None:
        args.skill_command = default_skill_command(repo)
    if args.checks is None:
        args.checks = default_check_commands(repo)
    skills = [load_skill(skill_root, name) for name in args.skills]

    progress_banner("skill_release_loop: configuration")
    progress_line(f"Repository: {repo}")
    progress_line(f"Run directory: {run_dir}")
    progress_line(f"Skill root: {skill_root}")
    progress_line(f"Skill pipeline: {' -> '.join(s.name for s in skills)}")
    progress_line(f"Max iterations: {args.max_iterations}")
    progress_line(f"Dry run: {args.dry_run}")
    progress_line(f"Skip push: {args.skip_push}")
    progress_line(f"Allow dirty worktree: {args.allow_dirty}")
    progress_line(f"Quiet (no streamed child output): {args.quiet}")
    progress_line(f"Skill command template:\n  {args.skill_command}")
    for i, check_cmd in enumerate(args.checks, start=1):
        progress_line(f"Check {i} template:\n  {check_cmd}")

    progress_banner("Preflight")
    progress_line("Decision: verify git repo (and clean worktree unless --allow-dirty or --dry-run).")
    ensure_repo_preflight(repo, args.allow_dirty, args.dry_run)
    progress_line("Preflight: OK")
    if not args.skip_push:
        progress_line(f"Decision: verify remote {args.remote!r} exists (push requested).")
        ensure_remote(repo, args.remote)
        progress_line("Preflight: remote OK")
    else:
        progress_line("Decision: skip remote check (--skip-push).")

    progress_banner("Skill/check loop")
    progress_line(
        "Decision tree: FOR iteration = 1 .. max_iterations: "
        "RUN all skills in order -> RUN all checks in order. "
        "IF every check exits 0 THEN break with success. "
        "ELSE IF iteration == max_iterations THEN fail. "
        "ELSE next iteration."
    )

    passed_iteration: int | None = None
    for iteration in range(1, args.max_iterations + 1):
        run_dir.mkdir(parents=True, exist_ok=True)
        run_skill_iteration(repo, skills, args, run_dir, iteration)
        if run_checks(repo, args, run_dir, iteration):
            passed_iteration = iteration
            break

    if passed_iteration is None:
        progress_banner("skill_release_loop: stopped")
        progress_line(
            f"Decision: checks did not all pass within {args.max_iterations} iteration(s) -> "
            "abort (no version bump, no tag, no push)."
        )
        raise LoopError(f"Checks did not pass after {args.max_iterations} iteration(s)")

    if args.dry_run:
        progress_banner("skill_release_loop: dry-run complete")
        progress_line(
            f"Decision: iteration {passed_iteration} succeeded under dry-run rules -> "
            "skip change detection, version bump, commit, tag, and push."
        )
        return 0

    progress_banner("Release gates (post-loop)")
    progress_line(
        f"Decision: iteration {passed_iteration} cleared checks -> validate release prerequisites, "
        "then bump patch version and create commit/tag."
    )

    changed_files = git_changed_files(repo)
    progress_line(f"Gate 1: working tree differs from HEAD in {len(changed_files)} path(s).")
    if not changed_files:
        raise LoopError("The skill loop produced no repository changes")
    if "CHANGELOG.md" not in changed_files:
        raise LoopError("CHANGELOG.md must be updated during the skill loop before a release can be cut")
    progress_line("Gate 2: CHANGELOG.md is among changed paths -> OK")

    version = current_version(repo)
    new_version = bump_patch(version)
    tag_name = f"v{new_version}"
    progress_line(f"Gate 3: bump {version!r} -> {new_version!r}; tag {tag_name!r} must not exist yet.")
    ensure_tag_absent(repo, tag_name)
    progress_line("Gate 3: OK")

    progress_line(f"Releasing: {version} -> {new_version} (iteration {passed_iteration} was last skill/check cycle).")

    finalize_changelog(repo, new_version, dt.date.today())
    replace_version(repo, new_version)
    create_release_commit(repo, new_version, args.commit_message)
    create_tag(repo, tag_name)
    if not args.skip_push:
        branch = args.branch or current_branch(repo)
        progress_line(f"Decision: push branch {branch!r} and tag {tag_name!r} to {args.remote!r}.")
        push_release(repo, args.remote, branch, tag_name)
        progress_line(f"Done: pushed {branch} and {tag_name} to {args.remote}.")
    else:
        progress_line("Decision: --skip-push -> leave commit and tag local only.")
        progress_line(f"Done: created local commit and tag {tag_name}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LoopError as exc:
        print(f"skill_release_loop: {exc}", file=sys.stderr)
        raise SystemExit(1)
