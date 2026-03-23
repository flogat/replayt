#!/usr/bin/env python3
"""Run repository skills in a loop, then cut a patch release when checks pass."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

_REPO_ROOT_FOR_SKILL_ENV = Path(__file__).resolve().parents[1]
_SRC_SKILL_ENV = str(_REPO_ROOT_FOR_SKILL_ENV / "src")
if _SRC_SKILL_ENV not in sys.path:
    sys.path.insert(0, _SRC_SKILL_ENV)

from replayt.cli.skill_loop_env import (  # noqa: E402
    SKILL_LOOP_FIX_INJECTED_ENV_KEYS,
    SKILL_LOOP_MAIN_INJECTED_ENV_KEYS,
)

# Default order: twelve feat_* skills, then review_design_fidelity, improvedoc, deslopdoc, reviewcodebase.
# Each feat_* skill targets one developer archetype (twelve skills instead of one bundled createfeatures step).
# .cursor/skills/REJECTION_BLOCKLIST.md records rejected ideas so skills do not repeat them.
# review_design_fidelity audits new code against the seven design principles and SCOPE.md and fixes drift
# before the broader review and doc passes.
DEFAULT_SKILLS = (
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
DEFAULT_TASK = (
    "Run the repository skill loop: twelve archetype-specific feature implementation skills "
    "(feat_staff_engineer, feat_junior_onboarding, feat_security_compliance, feat_ml_llm_engineer, "
    "feat_devops_sre, feat_product_engineer, feat_oss_maintainer, feat_startup_ic, "
    "feat_enterprise_integrator, feat_framework_enthusiast, feat_mcp_tooling, "
    "feat_agent_harness_engineer), then review_design_fidelity (audit "
    "new code against the 7 design principles and SCOPE.md, fix violations), then improvedoc "
    "(docs and repo improvements), deslopdoc (de-AI / humanize documentation), reviewcodebase "
    "(full repo review with fixes applied in-tree). Each feat_* skill reads "
    ".cursor/skills/REJECTION_BLOCKLIST.md to avoid re-proposing rejected ideas. Apply changes "
    "directly in the working tree, keep CHANGELOG.md updated under Unreleased, and leave the "
    "workspace ready for the outer release loop to bump the patch version, create the tag, and "
    "push once all checks pass."
)
FIX_CHECK_TASK = "Fix the failing check."
FIX_PRE_TAG_CI_TASK = "Fix the failure so pre-tag GitHub Actions verification passes."
SKILL_ALIASES = {
    "createfeature": "createfeatures",
    # Legacy alias: the old monolith skill still exists for manual invocation.
}
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
UNRELEASED_RE = re.compile(r"(?ms)^## Unreleased\s*$\n(?P<body>.*?)(?=^##\s|\Z)")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# Codex / ChatGPT CLI usage-limit messages often include a local "try again at" time.
TRY_AGAIN_AT_RE = re.compile(r"try\s+again\s+at\s+([^\n.]+)", re.IGNORECASE)

# Written to the end of each skill/check log so --resume can skip completed steps.
RUN_LOG_EXIT_RE = re.compile(r"^### skill_release_loop: exit_code=(\d+)\s*$", re.MULTILINE)
_SKILL_LOG_SHELL_CMD_RE = re.compile(r"^[$] .+$", re.MULTILINE)
RUN_DIR_STAMP_RE = re.compile(r"^\d{8}-\d{6}$")
LOG_BANNER_USAGE_RETRY = "--- skill_release_loop: retry after Codex usage-limit wait ---"
LOG_BANNER_RESUME = "--- skill_release_loop: resume ---"
# Written beside each *.prompt.md so harnesses can read the resolved contract without parsing Markdown.
SKILL_INVOCATION_SCHEMA = "replayt.skill_invocation.v1"
# Written once per run directory when the first skill step starts; stable for the whole run (--resume must match).
SKILL_RELEASE_PIPELINE_SCHEMA = "replayt.skill_release_pipeline.v1"

# Environment keys the loop sets for skill backends (GIT_CONFIG_* from safe.directory are separate).
class LoopError(RuntimeError):
    """Raised when the release loop cannot proceed safely."""


@dataclass(frozen=True)
class SkillSpec:
    requested_name: str
    name: str
    path: Path
    instructions: str


def _utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def skill_invocation_json_path(prompt_path: Path) -> Path:
    name = prompt_path.name
    if not name.endswith(".prompt.md"):
        raise LoopError(f"Expected a *.prompt.md path, got {prompt_path}")
    return prompt_path.with_name(f"{name[: -len('.prompt.md')]}.invocation.json")


def skill_pipeline_sha256(skill_names: list[str]) -> str:
    """Stable fingerprint for the ordered resolved skill folder names (UTF-8 newline join)."""

    return hashlib.sha256("\n".join(skill_names).encode("utf-8")).hexdigest()


def skill_command_template_sha256(skill_command: str) -> str:
    """SHA-256 hex digest of the raw ``--skill-command`` template (UTF-8), for argv-contract gates."""

    return hashlib.sha256(skill_command.encode("utf-8")).hexdigest()


def skill_loop_task_sha256(task: str) -> str:
    """SHA-256 hex digest of the shared ``--task`` string (UTF-8), for resume gates and outer-loop idempotency."""

    return hashlib.sha256(task.encode("utf-8")).hexdigest()


def path_under_repo_or_absolute(repo_root: str, target: str) -> str:
    """Path under *repo_root* when possible; else absolute (e.g. different Windows drive)."""

    root = Path(repo_root).resolve()
    resolved = Path(target).resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def skill_command_rel_placeholders(
    repo_root_resolved: str,
    *,
    prompt_file: str,
    log_file: str,
    invocation_file: str,
    run_dir: str,
) -> dict[str, str]:
    """Repo-relative paths for ``--skill-command`` templates (same strings as ``SKILL_*_REL`` env)."""

    return {
        "prompt_rel": path_under_repo_or_absolute(repo_root_resolved, prompt_file),
        "log_rel": path_under_repo_or_absolute(repo_root_resolved, log_file),
        "invocation_rel": path_under_repo_or_absolute(repo_root_resolved, invocation_file),
        "run_dir_rel": path_under_repo_or_absolute(repo_root_resolved, run_dir),
    }


def skill_release_run_stamp(run_dir: Path | str) -> str:
    """Basename of the skill-release run directory (``YYYYMMDD-HHMMSS`` for default new runs)."""

    return Path(run_dir).resolve().name


def ensure_skill_release_pipeline_file(
    run_dir: Path, skill_names: list[str], task: str, skill_command: str
) -> str:
    """Create run_dir/pipeline.json on first skill phase, or verify it matches --skills on resume."""

    sha = skill_pipeline_sha256(skill_names)
    cmd_sha = skill_command_template_sha256(skill_command)
    task_sha = skill_loop_task_sha256(task)
    path = run_dir / "pipeline.json"
    payload: dict[str, Any] = {
        "schema": SKILL_RELEASE_PIPELINE_SCHEMA,
        "skills": list(skill_names),
        "pipeline_sha256": sha,
        "skill_command_sha256": cmd_sha,
        "task": task,
        "task_sha256": task_sha,
        "run_stamp": skill_release_run_stamp(run_dir),
        "written_at": _utc_iso(),
    }
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LoopError(f"Invalid JSON in {path}: {exc}") from exc
        if existing.get("skills") != skill_names:
            raise LoopError(
                f"{path} lists skills {existing.get('skills')!r} but this run uses {skill_names!r}; "
                "use the same --skills as the original run or pick a fresh run directory."
            )
        if existing.get("pipeline_sha256") != sha:
            raise LoopError(
                f"{path} pipeline_sha256 {existing.get('pipeline_sha256')!r} != computed {sha!r}; "
                "refusing to continue."
            )
        existing_cmd_sha = existing.get("skill_command_sha256")
        if isinstance(existing_cmd_sha, str) and len(existing_cmd_sha) == 64:
            if existing_cmd_sha != cmd_sha:
                raise LoopError(
                    f"{path} skill_command_sha256 {existing_cmd_sha!r} != computed {cmd_sha!r}; "
                    "use the same --skill-command as the original run or pick a fresh run directory."
                )
        existing_task_sha = existing.get("task_sha256")
        if isinstance(existing_task_sha, str) and len(existing_task_sha) == 64:
            if existing_task_sha != task_sha:
                raise LoopError(
                    f"{path} task_sha256 {existing_task_sha!r} != computed {task_sha!r}; "
                    "use the same --task as the original run or pick a fresh run directory."
                )
        return sha
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return sha


def load_skill_release_pipeline_sha256(run_dir: Path) -> str:
    """Read pipeline_sha256 from a prior skill phase (checks and pre-tag fixes reuse the same value)."""

    path = run_dir / "pipeline.json"
    if not path.is_file():
        raise LoopError(
            f"Missing {path}; expected the skill phase to write it before this step. "
            "If you removed it, start a fresh run directory."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoopError(f"Invalid JSON in {path}: {exc}") from exc
    sha = data.get("pipeline_sha256")
    if not isinstance(sha, str) or len(sha) != 64:
        raise LoopError(f"{path} is missing a valid pipeline_sha256 field.")
    return sha


def load_skill_command_sha256_from_pipeline(run_dir: Path) -> str | None:
    """Return ``skill_command_sha256`` from *run_dir* / ``pipeline.json`` when present (legacy runs omit it)."""

    path = run_dir / "pipeline.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    val = data.get("skill_command_sha256")
    if isinstance(val, str) and len(val) == 64:
        return val
    return None


def effective_skill_command_sha256(run_dir: Path, skill_command: str) -> str:
    """Prefer the digest recorded in ``pipeline.json``; fall back to hashing the current ``--skill-command`` string."""

    return load_skill_command_sha256_from_pipeline(run_dir) or skill_command_template_sha256(skill_command)


def write_skill_invocation_json(
    *,
    prompt_path: Path,
    repo_root: str,
    skill_root: str,
    skill_name: str,
    skill_path: str,
    log_file: str,
    run_dir: str,
    injected_env_keys: tuple[str, ...],
    iteration: int,
    max_iterations: int,
    task: str,
    step_index: int,
    step_total: int,
    pipeline_sha256: str,
    skill_command_sha256: str,
    task_sha256: str,
    skill_requested_name: str | None = None,
) -> Path:
    """Atomically write machine-readable metadata for one skill / fix prompt invocation."""
    out = skill_invocation_json_path(prompt_path)
    prompt_abs = str(prompt_path.resolve())
    log_abs = str(Path(log_file).resolve())
    run_dir_abs = str(Path(run_dir).resolve())
    payload: dict[str, Any] = {
        "schema": SKILL_INVOCATION_SCHEMA,
        "repo_root": repo_root,
        "skill_root": skill_root,
        "skill_name": skill_name,
        "skill_path": skill_path,
        "pipeline_sha256": pipeline_sha256,
        "skill_command_sha256": skill_command_sha256,
        "task_sha256": task_sha256,
        "prompt_file": prompt_abs,
        "prompt_file_rel": path_under_repo_or_absolute(repo_root, prompt_abs),
        "log_file": log_abs,
        "log_file_rel": path_under_repo_or_absolute(repo_root, log_abs),
        "run_dir": run_dir_abs,
        "run_dir_rel": path_under_repo_or_absolute(repo_root, run_dir_abs),
        "run_stamp": skill_release_run_stamp(run_dir_abs),
        "injected_env_keys": sorted(injected_env_keys),
        "iteration": iteration,
        "max_iterations": max_iterations,
        "step_index": step_index,
        "step_total": step_total,
        "task": task,
        "written_at": _utc_iso(),
    }
    if skill_requested_name is not None:
        payload["skill_requested_name"] = skill_requested_name
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


class RunTracker:
    """Writes run_dir/status.json and log_dir/current.json so another shell can watch progress."""

    def __init__(self, repo: Path, run_dir: Path, log_dir_relative: Path) -> None:
        self.repo = repo
        self.run_dir = run_dir.resolve()
        self.current_path = (repo / log_dir_relative).resolve() / "current.json"
        self._lock = threading.Lock()
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self.state: dict[str, Any] = {
            "schema": "skill_release_loop/v1",
            "active": True,
            "pid": os.getpid(),
            "started_at": _utc_iso(),
        }

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                self.state[key] = _json_safe(value)
            self.state["updated_at"] = _utc_iso()
            self._write_unlocked()

    def _write_unlocked(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        status_path = self.run_dir / "status.json"
        tmp = status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(status_path)
        current_payload = {"run_dir": str(self.run_dir), **self.state}
        ctmp = self.current_path.with_suffix(".tmp")
        self.current_path.parent.mkdir(parents=True, exist_ok=True)
        ctmp.write_text(json.dumps(current_payload, indent=2) + "\n", encoding="utf-8")
        ctmp.replace(self.current_path)

    def start_heartbeat(self, *, interval_sec: float, waiting_on: str) -> None:
        self.stop_heartbeat()
        if interval_sec <= 0:
            return
        self._hb_stop.clear()

        def loop() -> None:
            while not self._hb_stop.wait(timeout=interval_sec):
                with self._lock:
                    self.state["heartbeat_at"] = _utc_iso()
                    self.state["waiting_on"] = waiting_on[:500]
                    self._write_unlocked()

        self._hb_thread = threading.Thread(target=loop, name="skill-release-heartbeat", daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=2.0)
        self._hb_thread = None
        with self._lock:
            self.state.pop("waiting_on", None)

    def finalize(self, *, outcome: str, error: str | None = None) -> None:
        self.stop_heartbeat()
        with self._lock:
            if "outcome" in self.state:
                return
            self.state["active"] = False
            self.state["outcome"] = outcome
            if error is not None:
                self.state["error"] = error
            self.state["finished_at"] = _utc_iso()
            self._write_unlocked()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the repository's skill prompts in order until checks pass, then bump the patch version, "
            "tag, and push."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The script is backend-agnostic. --skill-command runs once per skill and can use placeholders:\n"
            "  {skill} {skill_path} {skill_root} {prompt_file} {prompt_rel} {invocation_file} {invocation_rel} "
            "{log_file} {log_rel} {run_dir} {run_dir_rel} {run_stamp}\n"
            "  {repo} {iteration} {max_iterations} {task} {step_index} {step_total} {pipeline_sha256} "
            "{skill_command_sha256} {task_sha256}\n"
            "Quoted variants are also available via *_q (for example {prompt_file_q}).\n"
            "The same values are exported as environment variables prefixed with SKILL_ plus REPO_ROOT.\n"
            "Pipeline position within one iteration uses {step_index}/{step_total} (SKILL_STEP_*); "
            "fix prompts use 0/0. Outer retry loop uses {iteration}/{max_iterations} "
            "(SKILL_ITERATION / SKILL_MAX_ITERATIONS).\n"
            "Ordered --skills resolve to SKILL_PIPELINE_SHA256 / run_dir/pipeline.json "
            "(replayt.skill_release_pipeline.v1); resume fails fast if --skills order changes.\n"
            "Progress: prints configuration, a decision-tree summary, each command and log path, streamed "
            "child output (unless --quiet), and explicit decision lines after checks. Use --quiet for logs only.\n"
            "Codex usage limits: by default, if a skill log matches a usage-limit message and includes "
            "'try again at' with a time within --usage-limit-max-wait-seconds, the loop sleeps (status heartbeats "
            "continue) and retries the same skill; use --no-wait-on-codex-usage-limit to fail fast.\n"
            "Resume: use --resume to reuse a run directory and skip skills/checks whose logs already end with "
            "### skill_release_loop: exit_code=0. --resume with no argument picks the newest YYYYMMDD-HHMMSS folder "
            "under --log-dir that contains iter-*.log. Resume allows a dirty git worktree (same as --allow-dirty "
            "for preflight only). "
            "Logs from older runs without that footer are not skipped (re-run) unless you append "
            "`### skill_release_loop: exit_code=0` to finished skill logs manually.\n"
            "Default check #3 and pre-tag both run verify_github_action.py with --require-gh unless you pass "
            "--no-github-ci-verify-require-gh (so missing gh fails instead of skipping remote CI). "
            "Pre-tag failures run --skill-command fix/amend rounds (see --pre-tag-github-ci-max-fix-attempts).\n"
            "External monitor: updates .replayt/skill-release/current.json and <run-dir>/status.json (heartbeat "
            "while subprocesses run; see --status-interval)."
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
        "--release-count",
        type=int,
        default=1,
        help="Number of consecutive successful releases to create before exiting (default: 1).",
    )
    parser.add_argument(
        "--light",
        action="store_true",
        help="Run only dummy_changelog (smoke test); sets --max-iterations to 1 if still default 3.",
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
        "--pull-rebase-before-push",
        action="store_true",
        help=(
            "After the release commit, run `git fetch <remote>` and `git pull --rebase <remote> <branch>` "
            "before pre-tag CI and tagging, so local history matches the remote when it has moved ahead. "
            "Ignored with --skip-push."
        ),
    )
    parser.add_argument(
        "--no-pre-tag-github-ci",
        action="store_true",
        help="Skip verify_github_action after the release commit (before tag). For tests/offline.",
    )
    parser.add_argument(
        "--pre-tag-github-ci-max-fix-attempts",
        type=int,
        default=3,
        help=(
            "If pre-tag GitHub Actions verification fails after the release commit, run --skill-command to fix "
            "and amend that commit, then retry (default: 3). Use 0 to fail on the first verification failure."
        ),
    )
    parser.add_argument(
        "--github-ci-verify-require-gh",
        dest="github_ci_verify_require_gh",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "For default verify_github_action.py commands (check pipeline and pre-tag gate), pass --require-gh so a "
            "missing GitHub CLI fails the step instead of exiting 0 without running remote CI (default: on). "
            "Use --no-github-ci-verify-require-gh when gh is unavailable."
        ),
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
    parser.add_argument(
        "--status-interval",
        type=float,
        default=15.0,
        help=(
            "Seconds between heartbeat writes to status.json while a skill or check subprocess runs "
            "(default: 15). Set 0 to disable heartbeats."
        ),
    )
    parser.add_argument(
        "--wait-on-codex-usage-limit",
        dest="wait_on_codex_usage_limit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "If a skill fails with a Codex usage-limit message and a parsable 'try again at' time within "
            "--usage-limit-max-wait-seconds, sleep and retry the same skill (default: on)."
        ),
    )
    parser.add_argument(
        "--usage-limit-max-wait-seconds",
        type=float,
        default=86400.0,
        help="Maximum delay to honor for auto-retry (default: 86400 = 24h). Longer resets are not waited out.",
    )
    parser.add_argument(
        "--usage-limit-sleep-buffer-seconds",
        type=float,
        default=45.0,
        help="Extra seconds after the stated 'try again at' time before retrying (default: 45).",
    )
    parser.add_argument(
        "--usage-limit-max-waits-per-skill",
        type=int,
        default=100,
        help="Safety cap on usage-limit sleeps per skill invocation (default: 100).",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        metavar="RUN_DIR",
        help=(
            "Reuse a previous run directory: skip skills/checks whose logs end with exit_code=0. "
            "With no value, select the newest YYYYMMDD-HHMMSS folder under --log-dir that contains iter-*.log. "
            "Otherwise RUN_DIR is relative to --log-dir unless it is an absolute path. "
            "Implies allowing a dirty worktree for git preflight (same as --allow-dirty)."
        ),
    )
    args = parser.parse_args(argv)
    if getattr(args, "light", False):
        if not args.skills:
            args.skills = ["dummy_changelog"]
        args.task = "Create a dummy changelog entry under ## Unreleased to test the release loop."
        if args.max_iterations == 3:
            args.max_iterations = 1
    if args.max_iterations < 1:
        parser.error("--max-iterations must be >= 1")
    if args.release_count < 1:
        parser.error("--release-count must be >= 1")
    if args.status_interval < 0:
        parser.error("--status-interval must be >= 0")
    if args.usage_limit_max_wait_seconds <= 0:
        parser.error("--usage-limit-max-wait-seconds must be > 0")
    if args.usage_limit_sleep_buffer_seconds < 0:
        parser.error("--usage-limit-sleep-buffer-seconds must be >= 0")
    if args.usage_limit_max_waits_per_skill < 1:
        parser.error("--usage-limit-max-waits-per-skill must be >= 1")
    if args.pre_tag_github_ci_max_fix_attempts < 0:
        parser.error("--pre-tag-github-ci-max-fix-attempts must be >= 0")
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
    return f"{python_exe} {runner} --prompt-file {{prompt_file_q}} --skill-root {{skill_root_q}}"


def github_ci_verify_command(repo: Path, *, require_gh: bool) -> str:
    python_exe = quote_for_shell(str(repo_python(repo)))
    verify_script = quote_for_shell(str(repo / "scripts" / "verify_github_action.py"))
    if require_gh:
        return f"{python_exe} {verify_script} --require-gh"
    return f"{python_exe} {verify_script}"


def default_check_commands(repo: Path, *, github_ci_require_gh: bool) -> list[str]:
    python_exe = quote_for_shell(str(repo_python(repo)))
    ruff_exe = repo_ruff(repo)
    return [
        f"{ruff_exe} check src tests scripts",
        f"{python_exe} -m pytest",
        github_ci_verify_command(repo, require_gh=github_ci_require_gh),
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


def build_prompt(
    skill: SkillSpec,
    task: str,
    repo: Path,
    iteration: int,
    max_iterations: int,
    *,
    step_index: int,
    step_total: int,
) -> str:
    return (
        f"Repository root: {repo}\n"
        f"Skill: {skill.name}\n"
        f"Requested as: {skill.requested_name}\n"
        f"Iteration: {iteration}/{max_iterations}\n"
        f"Pipeline step: {step_index}/{step_total}\n\n"
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


def effective_allow_dirty(args: argparse.Namespace) -> bool:
    """Dirty worktree is expected when resuming a partial run; allow it without repeating --allow-dirty."""
    return bool(args.allow_dirty or args.resume is not None)


def ensure_repo_preflight(repo: Path, allow_dirty: bool, dry_run: bool) -> None:
    require_git_repo(repo)
    if dry_run or allow_dirty:
        return
    status = git_stdout(repo, ["status", "--porcelain"]).strip()
    if status:
        raise LoopError(
            "Working tree is not clean; commit or stash changes before running the release loop, "
            "or pass --allow-dirty (not needed when using --resume)."
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
    try:
        print(message, file=dest, end=end, flush=True)
    except UnicodeEncodeError:
        enc = getattr(dest, "encoding", None) or "utf-8"
        safe_msg = message.encode(enc, errors="replace").decode(enc)
        print(safe_msg, file=dest, end=end, flush=True)


def progress_banner(title: str, *, dest: TextIO = sys.stdout) -> None:
    progress_line("", dest=dest)
    progress_line(f"=== {title} ===", dest=dest)


def describe_skill_env_snippet(env: dict[str, str], *, task_max: int = 160) -> str:
    keys = (
        "REPO_ROOT",
        "SKILL_ROOT",
        "SKILL_NAME",
        "SKILL_ITERATION",
        "SKILL_STEP_INDEX",
        "SKILL_STEP_TOTAL",
        "SKILL_PIPELINE_SHA256",
        "SKILL_COMMAND_SHA256",
        "SKILL_PROMPT_FILE",
        "SKILL_PROMPT_REL",
        "SKILL_INVOCATION_FILE",
        "SKILL_INVOCATION_REL",
        "SKILL_LOG_FILE",
        "SKILL_LOG_REL",
        "SKILL_RUN_DIR",
        "SKILL_RUN_DIR_REL",
        "SKILL_RUN_STAMP",
        "SKILL_TASK_SHA256",
    )
    lines = [f"{k}={env.get(k, '')}" for k in keys]
    task = env.get("SKILL_TASK", "")
    if len(task) > task_max:
        task = task[: task_max - 3] + "..."
    lines.append(f"SKILL_TASK={task}")
    return "\n".join(lines)


def log_file_last_exit_code(text: str) -> int | None:
    last: int | None = None
    for match in RUN_LOG_EXIT_RE.finditer(text):
        last = int(match.group(1))
    return last


def log_path_last_exit_code(path: Path) -> int | None:
    if not path.is_file():
        return None
    return log_file_last_exit_code(path.read_text(encoding="utf-8", errors="replace"))


def iteration_fully_passed(
    run_dir: Path,
    iteration: int,
    skill_names: list[str],
    num_checks: int,
) -> bool:
    for name in skill_names:
        if log_path_last_exit_code(run_dir / f"iter-{iteration:02d}-{name}.log") != 0:
            return False
    for j in range(1, num_checks + 1):
        if log_path_last_exit_code(run_dir / f"iter-{iteration:02d}-check-{j:02d}.log") != 0:
            return False
    return True


def run_dir_is_resumable(
    run_dir: Path,
    skill_names: list[str],
    max_iterations: int,
    num_checks: int,
) -> bool:
    if not run_dir.is_dir() or not any(run_dir.glob("iter-*.log")):
        return False
    for it in range(1, max_iterations + 1):
        if iteration_fully_passed(run_dir, it, skill_names, num_checks):
            return False
    return True


def find_latest_resumable_run_dir(
    log_root: Path,
    skill_names: list[str],
    max_iterations: int,
    num_checks: int,
) -> Path | None:
    if not log_root.is_dir():
        return None
    candidates = sorted(
        (p for p in log_root.iterdir() if p.is_dir() and RUN_DIR_STAMP_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    for run_dir in candidates:
        if run_dir_is_resumable(run_dir, skill_names, max_iterations, num_checks):
            return run_dir
    return None


def find_latest_stamp_run_dir(log_root: Path) -> Path | None:
    """Newest ``YYYYMMDD-HHMMSS`` directory under *log_root* that has at least one ``iter-*.log`` file."""
    if not log_root.is_dir():
        return None
    candidates = sorted(
        (
            p
            for p in log_root.iterdir()
            if p.is_dir() and RUN_DIR_STAMP_RE.match(p.name) and any(p.glob("iter-*.log"))
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def resolve_run_directory(repo: Path, args: argparse.Namespace, skill_names: list[str]) -> Path:
    log_dir_resolved = (repo / args.log_dir).resolve()
    if args.resume is None:
        return (log_dir_resolved / dt.datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    if args.resume == "":
        found = find_latest_stamp_run_dir(log_dir_resolved)
        if found is None:
            raise LoopError(
                f"No prior run directory under {log_dir_resolved} "
                "(expected YYYYMMDD-HHMMSS folders with at least one iter-*.log file)."
            )
        return found
    run_candidate = Path(args.resume)
    run_dir = run_candidate.resolve() if run_candidate.is_absolute() else (log_dir_resolved / run_candidate).resolve()
    if not run_dir.is_dir():
        raise LoopError(f"Resume path is not a directory: {run_dir}")
    return run_dir


def last_skill_attempt_output_for_usage_scan(text: str) -> str:
    """Return captured output for the last `$ …` shell block (before its exit footer).

    Appended skill logs can contain multiple attempts; quota messages from an older attempt
    must not be treated as the latest failure.
    """
    footers = list(RUN_LOG_EXIT_RE.finditer(text))
    if not footers:
        return text
    last_footer_start = footers[-1].start()
    block = text[:last_footer_start]
    cmd_lines = list(_SKILL_LOG_SHELL_CMD_RE.finditer(block))
    if not cmd_lines:
        return text[last_footer_start:]
    last_cmd = cmd_lines[-1]
    return block[last_cmd.end() :].lstrip("\n")


def codex_usage_limit_log_detected(text: str) -> bool:
    lowered = text.lower()
    if "usage limit" in lowered:
        return True
    if "you've hit your usage" in lowered or "you have hit your usage" in lowered:
        return True
    if "hit your usage limit" in lowered:
        return True
    return False


def parse_try_again_at_local(text: str, *, now: dt.datetime | None = None) -> dt.datetime | None:
    """Parse 'try again at …' from Codex output (local TZ, today; next day if that time already passed)."""
    match = TRY_AGAIN_AT_RE.search(text)
    if not match:
        return None
    fragment = match.group(1).strip()
    if not fragment:
        return None
    local_now = now or dt.datetime.now().astimezone()
    tz = local_now.tzinfo or dt.datetime.now().astimezone().tzinfo
    if tz is None:
        tz = dt.timezone.utc
        local_now = local_now.replace(tzinfo=tz)

    clean_fragment = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", fragment, flags=re.IGNORECASE)
    full_formats = (
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M%p",
        "%b %d, %Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M%p",
        "%B %d, %Y %H:%M",
    )
    for fmt in full_formats:
        try:
            parsed = dt.datetime.strptime(clean_fragment, fmt)
            return parsed.replace(tzinfo=tz)
        except ValueError:
            continue

    time_only_formats = ("%I:%M %p", "%I:%M%p", "%H:%M")
    parsed_time: dt.time | None = None
    for fmt in time_only_formats:
        try:
            parsed_time = dt.datetime.strptime(fragment, fmt).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        return None
    candidate = dt.datetime.combine(local_now.date(), parsed_time, tzinfo=tz)
    if candidate <= local_now:
        candidate += dt.timedelta(days=1)
    return candidate


def compute_usage_limit_delay(
    now: dt.datetime,
    resume_at: dt.datetime,
    *,
    buffer_seconds: float,
    max_wait_seconds: float,
) -> float | None:
    """Seconds to sleep before retrying, or None if auto-wait is not allowed (too far in the future)."""
    if max_wait_seconds <= 0:
        raise LoopError("usage-limit max_wait_seconds must be > 0")
    if buffer_seconds < 0:
        raise LoopError("usage-limit buffer_seconds must be >= 0")
    wake_at = resume_at + dt.timedelta(seconds=buffer_seconds)
    delta = (wake_at - now).total_seconds()
    if delta > max_wait_seconds:
        return None
    return max(0.0, delta)


def sleep_until_with_heartbeat(
    seconds: float,
    *,
    tracker: RunTracker | None,
    heartbeat_interval: float,
    waiting_label: str,
    chunk_seconds: float = 30.0,
) -> None:
    """Sleep for ``seconds`` while optionally updating tracker heartbeats."""
    if seconds <= 0:
        return
    end = time.monotonic() + seconds
    if tracker is not None and heartbeat_interval > 0:
        tracker.start_heartbeat(interval_sec=heartbeat_interval, waiting_on=waiting_label)
    try:
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            if tracker is not None:
                tracker.update(usage_limit_sleep_remaining_sec=max(0.0, round(remaining, 1)))
            time.sleep(min(chunk_seconds, remaining))
    finally:
        if tracker is not None and heartbeat_interval > 0:
            tracker.stop_heartbeat()
            tracker.update(usage_limit_sleep_remaining_sec=None)


def run_shell_command(
    command: str,
    repo: Path,
    env: dict[str, str],
    *,
    log_path: Path | None = None,
    log_append: bool = False,
    log_section_banner: str | None = None,
    dry_run: bool = False,
    stream_to_terminal: bool = True,
    progress_label: str = "",
    expect_success: bool = True,
    tracker: RunTracker | None = None,
    heartbeat_interval: float = 0.0,
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

        if tracker is not None:
            tracker.start_heartbeat(interval_sec=heartbeat_interval, waiting_on=f"{progress_label}: {command}")
        try:
            mode = "a" if log_append else "w"
            banner = log_section_banner or LOG_BANNER_USAGE_RETRY
            with log_path.open(mode, encoding="utf-8") as handle:
                if log_append:
                    handle.write(f"\n\n{banner}\n$ {command}\n\n")
                else:
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
                if proc.stdout is None:
                    raise LoopError("Command stdout pipe was not captured; cannot stream child output to the log.")
                for line in proc.stdout:
                    handle.write(line)
                    if stream_to_terminal:
                        progress_line(f"{prefix}{line}", end="")
                return_code = proc.wait()
                handle.write(f"\n### skill_release_loop: exit_code={return_code}\n")
        finally:
            if tracker is not None:
                tracker.stop_heartbeat()

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
    tracker: RunTracker | None,
) -> None:
    resume = args.resume is not None
    progress_banner(f"Iteration {iteration}/{args.max_iterations}: skills")
    progress_line(
        "Decision: run each skill in sequence; each step invokes --skill-command with a fresh prompt file."
        + ("; resume skips steps whose logs end with exit_code=0." if resume else ".")
    )
    skill_names = [s.name for s in skills]
    pipeline_sha256 = ensure_skill_release_pipeline_file(run_dir, skill_names, args.task, args.skill_command)
    skill_cmd_sha = skill_command_template_sha256(args.skill_command)
    loop_task_sha = skill_loop_task_sha256(args.task)
    step_total = len(skills)
    for step_index, skill in enumerate(skills, start=1):
        stem = f"iter-{iteration:02d}-{skill.name}"
        prompt_path = run_dir / f"{stem}.prompt.md"
        log_path = run_dir / f"{stem}.log"
        if resume and log_path_last_exit_code(log_path) == 0:
            progress_line(f"Decision: resume; skip {skill.name} (prior exit_code=0): {log_path}")
            continue
        prompt_path.write_text(
            build_prompt(
                skill,
                args.task,
                repo,
                iteration,
                args.max_iterations,
                step_index=step_index,
                step_total=step_total,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        repo_resolved = str(repo.resolve())
        skill_root_resolved = str((repo / args.skill_root).resolve())
        run_dir_resolved = str(run_dir.resolve())
        run_stamp = skill_release_run_stamp(run_dir)
        invocation_path = write_skill_invocation_json(
            prompt_path=prompt_path,
            repo_root=repo_resolved,
            skill_root=skill_root_resolved,
            skill_name=skill.name,
            skill_path=str(skill.path),
            log_file=str(log_path),
            run_dir=run_dir_resolved,
            injected_env_keys=SKILL_LOOP_MAIN_INJECTED_ENV_KEYS,
            iteration=iteration,
            max_iterations=args.max_iterations,
            task=args.task,
            step_index=step_index,
            step_total=step_total,
            pipeline_sha256=pipeline_sha256,
            skill_command_sha256=skill_cmd_sha,
            task_sha256=loop_task_sha,
            skill_requested_name=skill.requested_name,
        )
        invocation_abs = str(invocation_path.resolve())
        # Inject safe.directory so child processes (e.g. Codex sandbox running as a
        # different OS user) can run git commands against the repo without
        # "dubious ownership" errors.  GIT_CONFIG_COUNT + KEY/VALUE is the
        # environment-based equivalent of `git -c safe.directory=...`.
        _inject_git_safe_directory(env, repo_resolved)
        env.update(
            {
                "REPO_ROOT": repo_resolved,
                "SKILL_ROOT": skill_root_resolved,
                "SKILL_NAME": skill.name,
                "SKILL_REQUESTED_NAME": skill.requested_name,
                "SKILL_PATH": str(skill.path),
                "SKILL_PROMPT_FILE": str(prompt_path),
                "SKILL_INVOCATION_FILE": invocation_abs,
                "SKILL_INVOCATION_REL": path_under_repo_or_absolute(repo_resolved, invocation_abs),
                "SKILL_LOG_FILE": str(log_path),
                "SKILL_ITERATION": str(iteration),
                "SKILL_MAX_ITERATIONS": str(args.max_iterations),
                "SKILL_TASK": args.task,
                "SKILL_RUN_DIR": run_dir_resolved,
                "SKILL_RUN_STAMP": run_stamp,
                "SKILL_STEP_INDEX": str(step_index),
                "SKILL_STEP_TOTAL": str(step_total),
                "SKILL_PIPELINE_SHA256": pipeline_sha256,
                "SKILL_COMMAND_SHA256": skill_cmd_sha,
                "SKILL_TASK_SHA256": loop_task_sha,
                "SKILL_PROMPT_REL": path_under_repo_or_absolute(repo_resolved, str(prompt_path)),
                "SKILL_LOG_REL": path_under_repo_or_absolute(repo_resolved, str(log_path)),
                "SKILL_RUN_DIR_REL": path_under_repo_or_absolute(repo_resolved, run_dir_resolved),
            }
        )
        command = render_command(
            args.skill_command,
            {
                "skill": skill.name,
                "skill_path": str(skill.path),
                "skill_root": skill_root_resolved,
                "prompt_file": str(prompt_path),
                "invocation_file": invocation_abs,
                "log_file": str(log_path),
                "run_dir": run_dir_resolved,
                "run_stamp": run_stamp,
                "repo": str(repo),
                "iteration": str(iteration),
                "max_iterations": str(args.max_iterations),
                "task": args.task,
                "step_index": str(step_index),
                "step_total": str(step_total),
                "pipeline_sha256": pipeline_sha256,
                "skill_command_sha256": skill_cmd_sha,
                "task_sha256": loop_task_sha,
                **skill_command_rel_placeholders(
                    repo_resolved,
                    prompt_file=str(prompt_path),
                    log_file=str(log_path),
                    invocation_file=invocation_abs,
                    run_dir=run_dir_resolved,
                ),
            },
        )
        progress_banner(f"Skill: {skill.name}")
        progress_line(f"Prompt written: {prompt_path}")
        progress_line(f"Skill definition: {skill.path}")
        if tracker is not None:
            tracker.update(
                phase="skill",
                iteration=iteration,
                max_iterations=args.max_iterations,
                skill=skill.name,
                prompt_file=prompt_path,
                log_file=log_path,
                command_preview=command[:500],
            )
        usage_waits = 0
        log_append = bool(resume and log_path.exists() and log_path.stat().st_size > 0)
        log_banner: str | None = LOG_BANNER_RESUME if log_append else None
        while True:
            completed = run_shell_command(
                command,
                repo,
                env,
                log_path=log_path,
                log_append=log_append,
                log_section_banner=log_banner,
                dry_run=args.dry_run,
                stream_to_terminal=not args.quiet,
                progress_label=f"skill:{skill.name}",
                expect_success=False,
                tracker=tracker,
                heartbeat_interval=args.status_interval,
            )
            if completed.returncode == 0:
                break
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            latest_attempt_log = last_skill_attempt_output_for_usage_scan(log_text)
            if (
                args.dry_run
                or not args.wait_on_codex_usage_limit
                or not codex_usage_limit_log_detected(latest_attempt_log)
            ):
                raise LoopError(
                    f"Command failed with exit code {completed.returncode}: {command}\nSee {log_path}"
                )
            resume_at = parse_try_again_at_local(latest_attempt_log)
            if resume_at is None:
                raise LoopError(
                    "Codex usage limit detected but no parsable 'try again at' time; "
                    f"fix quota or retry manually.\nSee {log_path}"
                )
            now = dt.datetime.now(resume_at.tzinfo)
            delay = compute_usage_limit_delay(
                now,
                resume_at,
                buffer_seconds=args.usage_limit_sleep_buffer_seconds,
                max_wait_seconds=args.usage_limit_max_wait_seconds,
            )
            if delay is None:
                raise LoopError(
                    f"Codex usage limit: retry time {resume_at.isoformat()} is more than "
                    f"{args.usage_limit_max_wait_seconds:.0f}s away; not auto-waiting.\nSee {log_path}"
                )
            usage_waits += 1
            if usage_waits > args.usage_limit_max_waits_per_skill:
                raise LoopError(
                    f"Exceeded --usage-limit-max-waits-per-skill ({args.usage_limit_max_waits_per_skill}) "
                    f"for {skill.name}; see {log_path}"
                )
            progress_banner(f"Skill: {skill.name} (Codex usage limit)")
            progress_line(
                f"Decision: usage limit detected; auto-continue after ~{delay:.0f}s "
                f"(stated resume ~{resume_at.isoformat()}, wait #{usage_waits})."
            )
            if tracker is not None:
                tracker.update(
                    phase="waiting_codex_usage_limit",
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                    skill=skill.name,
                    prompt_file=prompt_path,
                    log_file=log_path,
                    usage_limit_resume_at=resume_at.isoformat(),
                    usage_limit_wait_number=usage_waits,
                    command_preview=command[:500],
                )
            wait_label = (
                f"skill:{skill.name}:codex_usage_limit wait #{usage_waits} "
                f"~{int(delay)}s -> {resume_at.isoformat()}"
            )
            sleep_until_with_heartbeat(
                delay,
                tracker=tracker,
                heartbeat_interval=args.status_interval,
                waiting_label=wait_label[:500],
            )
            log_append = True
            log_banner = None
            if tracker is not None:
                tracker.update(
                    phase="skill",
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                    skill=skill.name,
                    prompt_file=prompt_path,
                    log_file=log_path,
                    command_preview=command[:500],
                )


def run_checks(
    repo: Path,
    args: argparse.Namespace,
    run_dir: Path,
    iteration: int,
    tracker: RunTracker | None,
) -> bool:
    resume = args.resume is not None
    progress_banner(f"Iteration {iteration}/{args.max_iterations}: checks")
    progress_line(
        f"Decision: run {len(args.checks)} check command(s) in order; all must exit 0 to finish the loop "
        "successfully."
        + ("; resume skips checks whose logs end with exit_code=0." if resume else ".")
    )
    pipeline_sha256 = load_skill_release_pipeline_sha256(run_dir)
    skill_cmd_sha = effective_skill_command_sha256(run_dir, args.skill_command)
    loop_task_sha = skill_loop_task_sha256(args.task)
    for index, template in enumerate(args.checks, start=1):
        log_path = run_dir / f"iter-{iteration:02d}-check-{index:02d}.log"
        if resume and log_path_last_exit_code(log_path) == 0:
            progress_line(f"Decision: resume; skip check {index} (prior exit_code=0): {log_path}")
            continue
        env = os.environ.copy()
        env["REPO_ROOT"] = str(repo)
        command = render_command(template, {"repo": str(repo), "iteration": str(iteration)})
        progress_banner(f"Check {index}/{len(args.checks)}")
        attempt = 0
        max_fix_attempts = 3
        chk_append = bool(resume and log_path.exists() and log_path.stat().st_size > 0)

        while True:
            if tracker is not None:
                tracker.update(
                    phase="check",
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                    check_index=index,
                    checks_total=len(args.checks),
                    log_file=log_path,
                    command_preview=command[:500],
                )
            if args.dry_run:
                run_shell_command(
                    command,
                    repo,
                    env,
                    log_path=log_path,
                    dry_run=True,
                    progress_label=f"check:{iteration:02d}-{index:02d}",
                    tracker=tracker,
                    heartbeat_interval=0.0,
                )
                progress_line("Decision: dry-run assumes this check would pass.")
                break
            chk_banner: str | None = LOG_BANNER_RESUME if chk_append else None
            completed = run_shell_command(
                command,
                repo,
                env,
                log_path=log_path,
                log_append=chk_append,
                log_section_banner=chk_banner,
                stream_to_terminal=not args.quiet,
                progress_label=f"check:{iteration:02d}-{index:02d}",
                expect_success=False,
                tracker=tracker,
                heartbeat_interval=args.status_interval,
            )
            if completed.returncode == 0:
                progress_line(f"Decision: check {index}/{len(args.checks)} passed -> continue.")
                break

            progress_line(
                f"Decision: check {index}/{len(args.checks)} failed (exit {completed.returncode})."
            )
            if attempt >= max_fix_attempts:
                progress_line(
                    f"Decision: max fix attempts ({max_fix_attempts}) reached. "
                    "Stop this iteration without releasing."
                )
                if iteration < args.max_iterations:
                    progress_line(f"Next: start iteration {iteration + 1} (skills run again from the top).")
                else:
                    progress_line("Next: no further iterations allowed (--max-iterations exhausted).")
                progress_line(f"Full output: {log_path}")
                return False

            progress_line(
                f"Next: spawning fix agent for check {index} (attempt {attempt + 1}/{max_fix_attempts})..."
            )

            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            tail_log = log_text[-4000:] if len(log_text) > 4000 else log_text

            fix_prompt_path = run_dir / f"iter-{iteration:02d}-check-{index:02d}-fix-{attempt+1}.prompt.md"
            fix_log_path = run_dir / f"iter-{iteration:02d}-check-{index:02d}-fix-{attempt+1}.log"

            fix_prompt_text = (
                f"The following check command failed with exit code {completed.returncode}:\n"
                f"`{command}`\n\n"
                f"Log output (tail):\n```text\n{tail_log}\n```\n\n"
                "Please analyze the failure and modify the codebase to fix the issues so the check passes.\n"
                "Apply repository changes directly in the working tree. Do not commit, tag, or push."
            )
            fix_prompt_path.write_text(fix_prompt_text, encoding="utf-8")
            run_dir_resolved = str(run_dir.resolve())
            run_stamp = skill_release_run_stamp(run_dir)
            fix_invocation_path = write_skill_invocation_json(
                prompt_path=fix_prompt_path,
                repo_root=str(repo.resolve()),
                skill_root=str((repo / args.skill_root).resolve()),
                skill_name="fix_check",
                skill_path="fix_check",
                log_file=str(fix_log_path),
                run_dir=run_dir_resolved,
                injected_env_keys=SKILL_LOOP_FIX_INJECTED_ENV_KEYS,
                iteration=iteration,
                max_iterations=args.max_iterations,
                task=FIX_CHECK_TASK,
                step_index=0,
                step_total=0,
                pipeline_sha256=pipeline_sha256,
                skill_command_sha256=skill_cmd_sha,
                task_sha256=loop_task_sha,
            )
            fix_invocation_abs = str(fix_invocation_path.resolve())
            repo_s = str(repo.resolve())

            fix_command = render_command(
                args.skill_command,
                {
                    "skill": "fix_check",
                    "skill_path": "fix_check",
                    "skill_root": str((repo / args.skill_root).resolve()),
                    "prompt_file": str(fix_prompt_path),
                    "invocation_file": fix_invocation_abs,
                    "log_file": str(fix_log_path),
                    "run_dir": run_dir_resolved,
                    "run_stamp": run_stamp,
                    "repo": str(repo),
                    "iteration": str(iteration),
                    "max_iterations": str(args.max_iterations),
                    "step_index": "0",
                    "step_total": "0",
                    "pipeline_sha256": pipeline_sha256,
                    "skill_command_sha256": skill_cmd_sha,
                    "task_sha256": loop_task_sha,
                    "task": FIX_CHECK_TASK,
                    **skill_command_rel_placeholders(
                        repo_s,
                        prompt_file=str(fix_prompt_path),
                        log_file=str(fix_log_path),
                        invocation_file=fix_invocation_abs,
                        run_dir=run_dir_resolved,
                    ),
                },
            )

            fix_env = os.environ.copy()
            _inject_git_safe_directory(fix_env, str(repo))
            fix_env.update(
                {
                    "REPO_ROOT": repo_s,
                    "SKILL_ROOT": str((repo / args.skill_root).resolve()),
                    "SKILL_NAME": "fix_check",
                    "SKILL_PROMPT_FILE": str(fix_prompt_path),
                    "SKILL_INVOCATION_FILE": fix_invocation_abs,
                    "SKILL_INVOCATION_REL": path_under_repo_or_absolute(repo_s, fix_invocation_abs),
                    "SKILL_LOG_FILE": str(fix_log_path),
                    "SKILL_ITERATION": str(iteration),
                    "SKILL_MAX_ITERATIONS": str(args.max_iterations),
                    "SKILL_TASK": FIX_CHECK_TASK,
                    "SKILL_RUN_DIR": run_dir_resolved,
                    "SKILL_RUN_STAMP": run_stamp,
                    "SKILL_STEP_INDEX": "0",
                    "SKILL_STEP_TOTAL": "0",
                    "SKILL_PIPELINE_SHA256": pipeline_sha256,
                    "SKILL_COMMAND_SHA256": skill_cmd_sha,
                    "SKILL_TASK_SHA256": loop_task_sha,
                    "SKILL_PROMPT_REL": path_under_repo_or_absolute(repo_s, str(fix_prompt_path)),
                    "SKILL_LOG_REL": path_under_repo_or_absolute(repo_s, str(fix_log_path)),
                    "SKILL_RUN_DIR_REL": path_under_repo_or_absolute(repo_s, run_dir_resolved),
                }
            )

            if tracker is not None:
                tracker.update(
                    phase="skill",
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                    skill="fix_check",
                    prompt_file=str(fix_prompt_path),
                    log_file=str(fix_log_path),
                    command_preview=fix_command[:500],
                )

            run_shell_command(
                fix_command,
                repo,
                fix_env,
                log_path=fix_log_path,
                stream_to_terminal=not args.quiet,
                progress_label=f"fix_check:{iteration:02d}-{index:02d}-{attempt+1}",
                expect_success=False,
                tracker=tracker,
                heartbeat_interval=args.status_interval,
            )

            chk_append = True
            attempt += 1
    progress_line(
        f"Decision: all checks passed on iteration {iteration} -> exit skill/check loop "
        "(proceed to dry-run summary or release gates)."
    )
    return True


def _inject_git_safe_directory(env: dict[str, str], repo_path: str) -> None:
    """Set ``safe.directory`` for *repo_path* via ``GIT_CONFIG_*`` environment variables.

    This is the environment-based equivalent of ``git -c safe.directory=<path>`` and ensures that
    **child processes** (e.g. a Codex sandbox running as a different OS user) can invoke git
    commands against *repo_path* without the "dubious ownership" error.

    If ``GIT_CONFIG_COUNT`` already exists in *env* the new entry is appended (the index is the
    current count value) so pre-existing config overrides are preserved.
    """
    idx = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{idx}"] = "safe.directory"
    env[f"GIT_CONFIG_VALUE_{idx}"] = repo_path
    env["GIT_CONFIG_COUNT"] = str(idx + 1)


def git_stdout(repo: Path, args: list[str]) -> str:
    completed = run_git(repo, args, capture_output=True)
    return completed.stdout


def _git_env() -> dict[str, str]:
    """Environment for git subprocesses: never inherit GIT_DIR / GIT_WORK_TREE from the parent.

    Those variables force Git to use a foreign object database; cwd=repo alone does not override
    them, so tags/commits could land in the wrong repository while Python edits files in repo.
    """
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def run_git(repo: Path, args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    repo_resolved = repo.resolve()
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repo_resolved}", "-C", str(repo_resolved), *args],
        cwd=repo,
        env=_git_env(),
        text=True,
        stdin=subprocess.DEVNULL,
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


def parse_unreleased_bullet_items(body: str) -> list[str]:
    """Parse top-level bullets under ``## Unreleased`` (same rules as ``scripts/changelog_unreleased.py``)."""
    items: list[str] = []
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("- "):
            if current:
                items.append("\n".join(current))
            current = [line[2:].strip()]
            continue
        if current and line.startswith("  "):
            current.append(line.strip())
            continue
        if current and not line.strip():
            current.append("")
    if current:
        items.append("\n".join(current).rstrip())
    return [item for item in items if item.strip()]


def unreleased_changelog_item_count(repo: Path) -> int | None:
    """Return bullet count under ``## Unreleased``, or ``None`` if CHANGELOG is missing or has no such section."""
    path = repo / "CHANGELOG.md"
    if not path.is_file():
        return None
    match = UNRELEASED_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        return None
    return len(parse_unreleased_bullet_items(match.group("body")))


def current_branch(repo: Path) -> str:
    branch = git_stdout(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch == "HEAD":
        raise LoopError("Detached HEAD is not supported for the release push")
    return branch


def ensure_remote(repo: Path, remote: str) -> None:
    run_git(repo, ["remote", "get-url", remote], capture_output=True)


_MAX_LOCAL_TAG_COLLISION_SKIPS = 512


def tag_exists_locally(repo: Path, tag_name: str) -> bool:
    repo_resolved = repo.resolve()
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo_resolved}",
            "-C",
            str(repo_resolved),
            "rev-parse",
            "-q",
            "--verify",
            f"refs/tags/{tag_name}",
        ],
        cwd=repo,
        env=_git_env(),
        text=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return result.returncode == 0


def next_patch_version_without_local_tag(repo: Path, base_version: str) -> str:
    candidate = bump_patch(base_version)
    collisions = 0
    while tag_exists_locally(repo, f"v{candidate}"):
        collisions += 1
        if collisions > _MAX_LOCAL_TAG_COLLISION_SKIPS:
            raise LoopError(
                "Could not find an unused local v* tag after "
                f"{_MAX_LOCAL_TAG_COLLISION_SKIPS} patch bump(s) starting from {bump_patch(base_version)!r}"
            )
        progress_line(f"Local tag v{candidate} already exists; bumping patch to next candidate.")
        candidate = bump_patch(candidate)
    return candidate


def ensure_tag_absent(repo: Path, tag_name: str) -> None:
    if tag_exists_locally(repo, tag_name):
        raise LoopError(f"Tag {tag_name} already exists")


def create_release_commit(repo: Path, new_version: str, commit_message_template: str) -> None:
    commit_message = commit_message_template.format(version=new_version)
    run_git(repo, ["add", "-A"])
    run_git(repo, ["commit", "-m", commit_message])


def create_tag(repo: Path, tag_name: str) -> None:
    run_git(repo, ["tag", "-a", tag_name, "-m", tag_name])


def pull_rebase_before_push(repo: Path, remote: str, branch: str) -> None:
    progress_line(
        f"Decision: --pull-rebase-before-push -> git fetch {remote!r}, then git pull --rebase "
        f"{remote!r} {branch!r}."
    )
    run_git(repo, ["fetch", remote], capture_output=True)
    run_git(repo, ["pull", "--rebase", remote, branch], capture_output=True)


def push_release(repo: Path, remote: str, branch: str, tag_name: str) -> None:
    # Push branch first: if the remote rejects it (e.g. non-fast-forward), avoid leaving only the tag there.
    try:
        run_git(repo, ["push", remote, f"HEAD:refs/heads/{branch}"], capture_output=True)
    except LoopError as exc:
        raise LoopError(
            f"{exc}\n"
            f"hint: integrate remote commits (e.g. `git fetch {remote}` then "
            f"`git pull --rebase {remote} {branch}`), then push the branch (and tag if needed). "
            f"On a future full release, pass `--pull-rebase-before-push` so the script rebases onto "
            f"{remote!r} after the release commit and before pre-tag CI and push. "
            f"If tag {tag_name!r} already exists on the remote from a partial push, delete or move it before "
            f"retrying."
        ) from exc
    run_git(repo, ["push", remote, f"refs/tags/{tag_name}"], capture_output=True)


def run_pre_tag_github_ci_with_fixes(
    repo: Path,
    args: argparse.Namespace,
    run_dir: Path,
    passed_iteration: int,
    tracker: RunTracker | None,
    verify_cmd: str,
    pre_tag_log: Path,
    gate_env: dict[str, str],
) -> None:
    max_fix = args.pre_tag_github_ci_max_fix_attempts
    fix_round = 0
    verify_append = False
    pipeline_sha256 = load_skill_release_pipeline_sha256(run_dir)
    skill_cmd_sha = effective_skill_command_sha256(run_dir, args.skill_command)
    loop_task_sha = skill_loop_task_sha256(args.task)

    while True:
        if tracker is not None:
            tracker.update(phase="pre_tag_github_ci", pre_tag_log_file=str(pre_tag_log))
        completed = run_shell_command(
            verify_cmd,
            repo,
            gate_env,
            log_path=pre_tag_log,
            stream_to_terminal=not args.quiet,
            progress_label=f"pre_tag_github_ci:{passed_iteration:02d}",
            expect_success=False,
            tracker=tracker,
            heartbeat_interval=args.status_interval,
            log_append=verify_append,
            log_section_banner=LOG_BANNER_RESUME if verify_append else None,
        )
        if completed.returncode == 0:
            return

        if max_fix == 0:
            raise LoopError(
                f"Pre-tag GitHub Actions verification failed (exit {completed.returncode}); see {pre_tag_log}."
            )
        if fix_round >= max_fix:
            raise LoopError(
                f"Pre-tag GitHub Actions verification failed (exit {completed.returncode}) after "
                f"{max_fix} fix round(s); see {pre_tag_log}."
            )

        progress_line(
            f"Decision: pre-tag verify failed (exit {completed.returncode}); "
            f"spawning fix agent (round {fix_round + 1}/{max_fix})..."
        )

        log_text = (
            pre_tag_log.read_text(encoding="utf-8", errors="replace") if pre_tag_log.is_file() else ""
        )
        tail_log = log_text[-4000:] if len(log_text) > 4000 else log_text

        fix_prompt_path = run_dir / f"pre-tag-iter-{passed_iteration:02d}-github-ci-fix-{fix_round + 1}.prompt.md"
        fix_log_path = run_dir / f"pre-tag-iter-{passed_iteration:02d}-github-ci-fix-{fix_round + 1}.log"

        fix_prompt_text = (
            f"The following pre-tag GitHub Actions verification command failed with exit code "
            f"{completed.returncode}:\n"
            f"`{verify_cmd}`\n\n"
            f"Log output (tail):\n```text\n{tail_log}\n```\n\n"
            "Please analyze the failure and modify the codebase so this verification passes when re-run.\n"
            "Apply repository changes directly in the working tree. Do not commit, tag, or push."
        )
        fix_prompt_path.write_text(fix_prompt_text, encoding="utf-8")
        run_dir_resolved = str(run_dir.resolve())
        run_stamp = skill_release_run_stamp(run_dir)
        pre_tag_invocation_path = write_skill_invocation_json(
            prompt_path=fix_prompt_path,
            repo_root=str(repo.resolve()),
            skill_root=str((repo / args.skill_root).resolve()),
            skill_name="fix_pre_tag_ci",
            skill_path="fix_pre_tag_ci",
            log_file=str(fix_log_path),
            run_dir=run_dir_resolved,
            injected_env_keys=SKILL_LOOP_FIX_INJECTED_ENV_KEYS,
            iteration=passed_iteration,
            max_iterations=args.max_iterations,
            task=FIX_PRE_TAG_CI_TASK,
            step_index=0,
            step_total=0,
            pipeline_sha256=pipeline_sha256,
            skill_command_sha256=skill_cmd_sha,
            task_sha256=loop_task_sha,
        )
        pre_tag_invocation_abs = str(pre_tag_invocation_path.resolve())
        repo_s = str(repo.resolve())

        fix_command = render_command(
            args.skill_command,
            {
                "skill": "fix_pre_tag_ci",
                "skill_path": "fix_pre_tag_ci",
                "skill_root": str((repo / args.skill_root).resolve()),
                "prompt_file": str(fix_prompt_path),
                "invocation_file": pre_tag_invocation_abs,
                "log_file": str(fix_log_path),
                "run_dir": run_dir_resolved,
                "run_stamp": run_stamp,
                "repo": str(repo),
                "iteration": str(passed_iteration),
                "max_iterations": str(args.max_iterations),
                "step_index": "0",
                "step_total": "0",
                "pipeline_sha256": pipeline_sha256,
                "skill_command_sha256": skill_cmd_sha,
                "task_sha256": loop_task_sha,
                "task": FIX_PRE_TAG_CI_TASK,
                **skill_command_rel_placeholders(
                    repo_s,
                    prompt_file=str(fix_prompt_path),
                    log_file=str(fix_log_path),
                    invocation_file=pre_tag_invocation_abs,
                    run_dir=run_dir_resolved,
                ),
            },
        )

        fix_env = os.environ.copy()
        _inject_git_safe_directory(fix_env, str(repo))
        fix_env.update(
            {
                "REPO_ROOT": repo_s,
                "SKILL_ROOT": str((repo / args.skill_root).resolve()),
                "SKILL_NAME": "fix_pre_tag_ci",
                "SKILL_PROMPT_FILE": str(fix_prompt_path),
                "SKILL_INVOCATION_FILE": pre_tag_invocation_abs,
                "SKILL_INVOCATION_REL": path_under_repo_or_absolute(repo_s, pre_tag_invocation_abs),
                "SKILL_LOG_FILE": str(fix_log_path),
                "SKILL_ITERATION": str(passed_iteration),
                "SKILL_MAX_ITERATIONS": str(args.max_iterations),
                "SKILL_TASK": FIX_PRE_TAG_CI_TASK,
                "SKILL_RUN_DIR": run_dir_resolved,
                "SKILL_RUN_STAMP": run_stamp,
                "SKILL_STEP_INDEX": "0",
                "SKILL_STEP_TOTAL": "0",
                "SKILL_PIPELINE_SHA256": pipeline_sha256,
                "SKILL_COMMAND_SHA256": skill_cmd_sha,
                "SKILL_TASK_SHA256": loop_task_sha,
                "SKILL_PROMPT_REL": path_under_repo_or_absolute(repo_s, str(fix_prompt_path)),
                "SKILL_LOG_REL": path_under_repo_or_absolute(repo_s, str(fix_log_path)),
                "SKILL_RUN_DIR_REL": path_under_repo_or_absolute(repo_s, run_dir_resolved),
            }
        )

        if tracker is not None:
            tracker.update(
                phase="pre_tag_github_ci_fix",
                iteration=passed_iteration,
                max_iterations=args.max_iterations,
                skill="fix_pre_tag_ci",
                prompt_file=str(fix_prompt_path),
                log_file=str(fix_log_path),
                command_preview=fix_command[:500],
            )

        run_shell_command(
            fix_command,
            repo,
            fix_env,
            log_path=fix_log_path,
            stream_to_terminal=not args.quiet,
            progress_label=f"fix_pre_tag_ci:{passed_iteration:02d}-{fix_round + 1}",
            expect_success=False,
            tracker=tracker,
            heartbeat_interval=args.status_interval,
        )

        if not git_changed_files(repo):
            raise LoopError(
                f"Pre-tag CI fix produced no working tree changes after verify exit {completed.returncode}; "
                f"see {fix_log_path}."
            )

        run_git(repo, ["add", "-A"])
        run_git(repo, ["commit", "--amend", "--no-edit"])

        fix_round += 1
        verify_append = True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path.cwd().resolve()
    skill_root = (repo / args.skill_root).resolve()
    if args.skill_command is None:
        args.skill_command = default_skill_command(repo)
    if args.checks is None:
        args.checks = default_check_commands(repo, github_ci_require_gh=args.github_ci_verify_require_gh)
    skills = [load_skill(skill_root, name) for name in args.skills]
    skill_names = [s.name for s in skills]

    for release_index in range(1, args.release_count + 1):
        if args.release_count > 1:
            progress_banner(f"Release loop {release_index}/{args.release_count}")

        try:
            run_dir = resolve_run_directory(repo, args, skill_names)
        except LoopError as exc:
            print(f"skill_release_loop: {exc}", file=sys.stderr)
            return 1

        tracker = RunTracker(repo, run_dir, Path(args.log_dir))

        try:
            _main_run(repo, skill_root, run_dir, skills, args, tracker)
        except LoopError as exc:
            tracker.finalize(outcome="failed", error=str(exc))
            raise
        except KeyboardInterrupt:
            if tracker.state.get("active", False):
                tracker.finalize(outcome="interrupted", error="keyboard interrupt")
            raise
        except Exception as exc:
            if tracker.state.get("active", False):
                tracker.finalize(outcome="interrupted", error=f"{type(exc).__name__}: {exc}")
            raise

        if release_index < args.release_count:
            if args.resume is not None:
                args.resume = None
            time.sleep(1.2)

    return 0


def _main_run(
    repo: Path,
    skill_root: Path,
    run_dir: Path,
    skills: list[SkillSpec],
    args: argparse.Namespace,
    tracker: RunTracker,
) -> None:
    progress_banner("skill_release_loop: configuration")
    progress_line(f"Repository: {repo}")
    progress_line(f"Run directory: {run_dir}")
    progress_line(f"External monitor (stable path): {tracker.current_path}")
    progress_line(f"Run status (this run only): {run_dir / 'status.json'}")
    progress_line(f"Skill root: {skill_root}")
    progress_line(f"Skill pipeline: {' -> '.join(s.name for s in skills)}")
    progress_line(f"Skill pipeline fingerprint: {skill_pipeline_sha256([s.name for s in skills])}")
    progress_line(f"Max iterations: {args.max_iterations}")
    progress_line(f"Dry run: {args.dry_run}")
    progress_line(f"Skip push: {args.skip_push}")
    progress_line(f"Pull rebase before push: {args.pull_rebase_before_push}")
    dirty_ok = effective_allow_dirty(args)
    progress_line(
        f"Allow dirty worktree: {dirty_ok}"
        + (
            " (implicit: --resume)"
            if dirty_ok and not args.allow_dirty and args.resume is not None
            else ""
        )
    )
    progress_line(f"Quiet (no streamed child output): {args.quiet}")
    if args.resume is not None:
        progress_line(f"Resume: reusing run directory {run_dir}")
    progress_line(f"Wait on Codex usage limit (auto-retry): {args.wait_on_codex_usage_limit}")
    progress_line(
        f"Usage-limit max wait: {args.usage_limit_max_wait_seconds:.0f}s; "
        f"buffer after stated time: {args.usage_limit_sleep_buffer_seconds:.0f}s; "
        f"max waits per skill: {args.usage_limit_max_waits_per_skill}"
    )
    progress_line(f"Skill command template:\n  {args.skill_command}")
    progress_line(f"Default GitHub Actions verify passes --require-gh: {args.github_ci_verify_require_gh}")
    for i, check_cmd in enumerate(args.checks, start=1):
        progress_line(f"Check {i} template:\n  {check_cmd}")

    progress_banner("Preflight")
    progress_line(
        "Decision: verify git repo (clean worktree unless --dry-run, --allow-dirty, or --resume)."
    )
    ensure_repo_preflight(repo, dirty_ok, args.dry_run)
    progress_line("Preflight: OK")
    if not args.skip_push:
        progress_line(f"Decision: verify remote {args.remote!r} exists (push requested).")
        ensure_remote(repo, args.remote)
        progress_line("Preflight: remote OK")
    else:
        progress_line("Decision: skip remote check (--skip-push).")

    tracker.update(
        phase="configured",
        repo=str(repo),
        run_dir=str(run_dir),
        dry_run=args.dry_run,
        skip_push=args.skip_push,
        allow_dirty=dirty_ok,
        max_iterations=args.max_iterations,
        skill_pipeline=[s.name for s in skills],
        skill_command=args.skill_command,
        checks=list(args.checks),
        status_interval_sec=args.status_interval,
        wait_on_codex_usage_limit=args.wait_on_codex_usage_limit,
        usage_limit_max_wait_seconds=args.usage_limit_max_wait_seconds,
        usage_limit_sleep_buffer_seconds=args.usage_limit_sleep_buffer_seconds,
        usage_limit_max_waits_per_skill=args.usage_limit_max_waits_per_skill,
        resume=args.resume is not None,
        github_ci_verify_require_gh=args.github_ci_verify_require_gh,
    )

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
        tracker.update(phase="iteration_skills", iteration=iteration, step="skills")
        run_skill_iteration(repo, skills, args, run_dir, iteration, tracker)
        tracker.update(phase="iteration_checks", iteration=iteration, step="checks")
        if run_checks(repo, args, run_dir, iteration, tracker):
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
        tracker.finalize(outcome="dry_run_complete")
        return

    progress_banner("Release gates (post-loop)")
    progress_line(
        f"Decision: iteration {passed_iteration} cleared checks -> validate release prerequisites, "
        "then bump patch version and create commit/tag."
    )
    tracker.update(phase="release_gates", passed_iteration=passed_iteration)

    changed_files = git_changed_files(repo)
    progress_line(f"Gate 1: working tree differs from HEAD in {len(changed_files)} path(s).")
    if not changed_files:
        raise LoopError("The skill loop produced no repository changes")
    if "CHANGELOG.md" not in changed_files:
        if args.resume is not None:
            ur_count = unreleased_changelog_item_count(repo)
            if ur_count is None:
                raise LoopError(
                    "CHANGELOG.md must be updated during the skill loop before a release can be cut "
                    "(on --resume: missing CHANGELOG.md or ## Unreleased section)."
                )
            if ur_count < 1:
                raise LoopError(
                    "CHANGELOG.md must be updated during the skill loop before a release can be cut "
                    "(on --resume: add at least one bullet under ## Unreleased, or edit CHANGELOG.md)."
                )
            progress_line(
                f"Gate 2: resume; CHANGELOG.md unchanged vs HEAD; ## Unreleased has {ur_count} bullet item(s) -> OK"
            )
        else:
            raise LoopError("CHANGELOG.md must be updated during the skill loop before a release can be cut")
    else:
        progress_line("Gate 2: CHANGELOG.md is among changed paths -> OK")

    version = current_version(repo)
    first_bump = bump_patch(version)
    new_version = next_patch_version_without_local_tag(repo, version)
    tag_name = f"v{new_version}"
    if new_version != first_bump:
        progress_line(
            f"Gate 3: bump {version!r} -> {new_version!r} (skipped occupied local tags through v{first_bump!r}); "
            f"tag {tag_name!r} must not exist yet."
        )
    else:
        progress_line(f"Gate 3: bump {version!r} -> {new_version!r}; tag {tag_name!r} must not exist yet.")
    ensure_tag_absent(repo, tag_name)
    progress_line("Gate 3: OK")

    progress_line(f"Releasing: {version} -> {new_version} (iteration {passed_iteration} was last skill/check cycle).")

    finalize_changelog(repo, new_version, dt.date.today())
    replace_version(repo, new_version)
    create_release_commit(repo, new_version, args.commit_message)

    if args.pull_rebase_before_push:
        if args.skip_push:
            progress_line("Decision: --pull-rebase-before-push ignored (--skip-push).")
        else:
            branch_for_sync = args.branch or current_branch(repo)
            pull_rebase_before_push(repo, args.remote, branch_for_sync)

    if not args.no_pre_tag_github_ci:
        progress_banner("Pre-tag GitHub Actions CI")
        pre_tag_log = run_dir / f"pre-tag-iter-{passed_iteration:02d}-github-ci.log"
        verify_cmd = render_command(
            github_ci_verify_command(repo, require_gh=args.github_ci_verify_require_gh),
            {"repo": str(repo), "iteration": str(passed_iteration)},
        )
        gate_env = os.environ.copy()
        _inject_git_safe_directory(gate_env, str(repo))
        gate_env["REPO_ROOT"] = str(repo)
        run_pre_tag_github_ci_with_fixes(
            repo, args, run_dir, passed_iteration, tracker, verify_cmd, pre_tag_log, gate_env
        )

    create_tag(repo, tag_name)
    if not args.skip_push:
        branch = args.branch or current_branch(repo)
        progress_line(f"Decision: push branch {branch!r} and tag {tag_name!r} to {args.remote!r}.")
        tracker.update(phase="push", branch=branch, tag=tag_name, remote=args.remote)
        push_release(repo, args.remote, branch, tag_name)
        progress_line(f"Done: pushed {branch} and {tag_name} to {args.remote}.")
        tracker.finalize(outcome="released")
    else:
        progress_line("Decision: --skip-push -> leave commit and tag local only.")
        progress_line(f"Done: created local commit and tag {tag_name}.")
        tracker.finalize(outcome="released_local")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LoopError as exc:
        print(f"skill_release_loop: {exc}", file=sys.stderr)
        raise SystemExit(1)
