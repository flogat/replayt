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

DEFAULT_SKILLS = ("createfeatures", "improvedoc", "deslopdoc", "reviewcodebase")
DEFAULT_TASK = (
    "Run the repository skill loop in this order: createfeatures, improvedoc, deslopdoc, "
    "reviewcodebase. Apply the changes directly in the repo, keep CHANGELOG.md updated under "
    "Unreleased, and leave the workspace ready for the outer release loop to bump the patch "
    "version, create the tag, and push once all checks pass."
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
            "The same values are exported as environment variables prefixed with SKILL_ plus REPO_ROOT."
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
    if not allow_dirty and not dry_run:
        status = git_stdout(repo, ["status", "--porcelain"])
        if status.strip():
            raise LoopError("Refusing to run on a dirty worktree. Commit or stash changes first, or use --allow-dirty.")


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


def run_shell_command(
    command: str,
    repo: Path,
    env: dict[str, str],
    *,
    log_path: Path | None = None,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    if dry_run:
        print(f"[dry-run] {command}")
        return subprocess.CompletedProcess(command, 0, "", "")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"$ {command}\n\n")
            result = subprocess.run(
                command,
                cwd=repo,
                env=env,
                shell=True,
                text=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        if result.returncode != 0:
            raise LoopError(f"Command failed with exit code {result.returncode}: {command}\nSee {log_path}")
        return subprocess.CompletedProcess(command, result.returncode, "", "")
    result = subprocess.run(command, cwd=repo, env=env, shell=True, text=True)
    if result.returncode != 0:
        raise LoopError(f"Command failed with exit code {result.returncode}: {command}")
    return result


def run_skill_iteration(
    repo: Path,
    skills: list[SkillSpec],
    args: argparse.Namespace,
    run_dir: Path,
    iteration: int,
) -> None:
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
        print(f"Running skill {skill.name} ({iteration}/{args.max_iterations})")
        run_shell_command(command, repo, env, log_path=log_path, dry_run=args.dry_run)


def run_checks(repo: Path, args: argparse.Namespace, run_dir: Path, iteration: int) -> bool:
    for index, template in enumerate(args.checks, start=1):
        log_path = run_dir / f"iter-{iteration:02d}-check-{index:02d}.log"
        env = os.environ.copy()
        env["REPO_ROOT"] = str(repo)
        command = render_command(template, {"repo": str(repo), "iteration": str(iteration)})
        print(f"Running check {index}/{len(args.checks)} after iteration {iteration}")
        if args.dry_run:
            run_shell_command(command, repo, env, log_path=log_path, dry_run=True)
            continue
        result = subprocess.run(
            command,
            cwd=repo,
            env=env,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_path.write_text(f"$ {command}\n\n{result.stdout}", encoding="utf-8")
        if result.returncode != 0:
            print(f"Check failed: {command}")
            print(f"See {log_path}")
            return False
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

    ensure_repo_preflight(repo, args.allow_dirty, args.dry_run)
    if not args.skip_push:
        ensure_remote(repo, args.remote)

    passed_iteration: int | None = None
    for iteration in range(1, args.max_iterations + 1):
        run_dir.mkdir(parents=True, exist_ok=True)
        run_skill_iteration(repo, skills, args, run_dir, iteration)
        if run_checks(repo, args, run_dir, iteration):
            passed_iteration = iteration
            break

    if passed_iteration is None:
        raise LoopError(f"Checks did not pass after {args.max_iterations} iteration(s)")

    changed_files = git_changed_files(repo)
    if not changed_files:
        raise LoopError("The skill loop produced no repository changes")
    if "CHANGELOG.md" not in changed_files:
        raise LoopError("CHANGELOG.md must be updated during the skill loop before a release can be cut")

    version = current_version(repo)
    new_version = bump_patch(version)
    tag_name = f"v{new_version}"
    ensure_tag_absent(repo, tag_name)

    print(f"Checks passed after iteration {passed_iteration}; releasing {version} -> {new_version}")
    if args.dry_run:
        print(f"[dry-run] Would update CHANGELOG.md, bump version files, create {tag_name}, and push to {args.remote}")
        return 0

    finalize_changelog(repo, new_version, dt.date.today())
    replace_version(repo, new_version)
    create_release_commit(repo, new_version, args.commit_message)
    create_tag(repo, tag_name)
    if not args.skip_push:
        branch = args.branch or current_branch(repo)
        push_release(repo, args.remote, branch, tag_name)
        print(f"Pushed {branch} and {tag_name} to {args.remote}")
    else:
        print(f"Created local release commit and tag {tag_name}; push skipped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LoopError as exc:
        print(f"skill_release_loop: {exc}", file=sys.stderr)
        raise SystemExit(1)
