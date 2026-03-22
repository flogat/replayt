#!/usr/bin/env python3
"""Verify that the current working tree changes pass GitHub Actions CI.

Uses ``git stash`` so that after the temp branch is deleted, the original uncommitted
working tree (including edits from the skill loop) is restored. A naive
``checkout main`` + ``reset --soft`` sequence drops those edits and can rewind the
wrong commit.

All ``git`` and ``gh`` subprocesses use ``cwd`` set to the repository root from
``git rev-parse --show-toplevel``, so the script still targets the correct repo when invoked
via an absolute path while the shell cwd is outside that tree.

Requirements: git. For remote workflow verification, ``gh`` must be available (authenticated).
Resolution order: ``REPLAYT_GH`` / ``GH_EXE`` (full path), :func:`shutil.which`, then common
install locations on Windows and macOS. IDE-integrated shells sometimes omit the GitHub CLI
directory from ``PATH`` even when ``gh`` works in a normal terminal.

If ``gh`` cannot be resolved, the script skips and exits 0 unless ``--require-gh`` is set.
``ci.yml`` should include ``workflow_dispatch``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def resolve_git_repo_root() -> Path:
    """Return the absolute git work tree root (``git rev-parse --show-toplevel``)."""

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stdin=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        msg = "Not a git repository, or git is unavailable (need git rev-parse --show-toplevel)."
        raise RuntimeError(msg) from exc
    return Path(out).resolve()


def resolve_gh_executable() -> str | None:
    """Return a path to ``gh`` suitable for ``subprocess``, or None if not found."""
    for key in ("REPLAYT_GH", "GH_EXE"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())

    found = shutil.which("gh")
    if found:
        return found

    candidates: list[Path] = []
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app = (os.environ.get("LOCALAPPDATA") or "").strip()
        candidates.extend(
            [
                Path(program_files) / "GitHub CLI" / "gh.exe",
                Path(program_files_x86) / "GitHub CLI" / "gh.exe",
            ]
        )
        if local_app:
            candidates.append(Path(local_app) / "Programs" / "GitHub CLI" / "gh.exe")
    elif sys.platform == "darwin":
        candidates.extend([Path("/opt/homebrew/bin/gh"), Path("/usr/local/bin/gh")])

    for path in candidates:
        try:
            if path.is_file():
                resolved = str(path.resolve())
                print(
                    f"[verify_github_action] Resolved gh outside PATH: {resolved}",
                    file=sys.stderr,
                )
                return resolved
        except OSError:
            continue
    return None


def run(
    cmd: list[str],
    *,
    cwd: str,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {"check": check, "cwd": cwd, "stdin": subprocess.DEVNULL}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def run_out(cmd: list[str], *, cwd: str) -> str:
    return subprocess.check_output(cmd, text=True, cwd=cwd, stdin=subprocess.DEVNULL).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify GitHub Actions CI before releasing.")
    parser.add_argument("--workflow", default="ci.yml", help="Workflow file to trigger (default: ci.yml).")
    parser.add_argument("--remote", default="origin", help="Git remote (default: origin).")
    parser.add_argument("--poll-interval", type=float, default=20.0, help="Poll interval seconds (default: 20).")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Max wait seconds (default: 1800).")
    parser.add_argument(
        "--require-gh",
        action="store_true",
        help=(
            "Exit with code 1 if the GitHub CLI (gh) cannot be resolved (PATH, REPLAYT_GH / GH_EXE, "
            "or standard install locations; default: skip verification and exit 0)."
        ),
    )
    args = parser.parse_args(argv)

    gh_exe = resolve_gh_executable()
    if gh_exe is None:
        msg = (
            "[verify_github_action] GitHub CLI (gh) not found; cannot trigger or poll workflow runs. "
            "Install https://cli.github.com/, add gh to PATH, or set REPLAYT_GH (or GH_EXE) to the full path "
            "to gh.exe / gh."
        )
        if args.require_gh:
            print(msg, file=sys.stderr)
            return 1
        print(f"{msg} Skipping verification (exit 0). Use --require-gh to fail instead.")
        return 0

    try:
        repo_cwd = str(resolve_git_repo_root())
    except RuntimeError as exc:
        print(f"[verify_github_action] ERROR: {exc}", file=sys.stderr)
        return 1

    original_branch = run_out(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_cwd)
    timestamp = int(time.time())
    temp_branch = f"tmp-ci-verify-{timestamp}"
    stash_message = f"replayt-verify-ci-{timestamp}"

    dirty = run_out(["git", "status", "--porcelain"], cwd=repo_cwd)
    has_staged = bool(run_out(["git", "diff", "--cached", "--name-only"], cwd=repo_cwd))
    has_wip = bool(dirty) or has_staged

    print(f"[verify_github_action] Original branch: {original_branch}")
    print(f"[verify_github_action] Temp branch: {temp_branch}")

    stash_pushed = False
    if has_wip:
        run(["git", "stash", "push", "-u", "-m", stash_message], cwd=repo_cwd)
        stash_pushed = True
        print("[verify_github_action] Stashed working tree (including untracked) for CI branch.")

    ci_passed = False
    run_id: str | None = None

    try:
        run(["git", "checkout", "-b", temp_branch], cwd=repo_cwd)
        if stash_pushed:
            applied = run(["git", "stash", "apply"], cwd=repo_cwd, check=False, capture=True)
            if applied.returncode != 0:
                print(
                    "[verify_github_action] ERROR: git stash apply failed; resolve conflicts, then retry.\n"
                    + (applied.stderr or ""),
                    file=sys.stderr,
                )
                return 1
            run(["git", "add", "-A"], cwd=repo_cwd)
            run(["git", "commit", "-m", f"temp: ci verify {timestamp}"], cwd=repo_cwd)

        run(["git", "push", "-u", args.remote, temp_branch], cwd=repo_cwd)
        print(f"[verify_github_action] Pushed temp branch {temp_branch} to {args.remote}.")

        result = run(
            [gh_exe, "workflow", "run", args.workflow, "--ref", temp_branch],
            cwd=repo_cwd,
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            print(
                "[verify_github_action] Warning: gh workflow run exited "
                f"{result.returncode}: {(result.stderr or '').strip()}"
            )

        print("[verify_github_action] Waiting for GitHub to register the run...")
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(args.poll_interval)
            list_result = run(
                [
                    gh_exe,
                    "run",
                    "list",
                    "--workflow",
                    args.workflow,
                    "--branch",
                    temp_branch,
                    "--limit",
                    "1",
                    "--json",
                    "databaseId,status,conclusion",
                ],
                cwd=repo_cwd,
                check=False,
                capture=True,
            )
            if list_result.returncode != 0 or not list_result.stdout.strip() or list_result.stdout.strip() == "[]":
                print("[verify_github_action] No runs found yet, polling...")
                continue
            try:
                runs = json.loads(list_result.stdout)
            except json.JSONDecodeError:
                print("[verify_github_action] Could not parse gh run list JSON; polling...", file=sys.stderr)
                continue
            if not runs:
                print("[verify_github_action] No runs found yet, polling...")
                continue
            row = runs[0]
            if not isinstance(row, dict):
                print(
                    "[verify_github_action] Unexpected gh run list JSON (non-object row); polling...",
                    file=sys.stderr,
                )
                continue
            db_id = row.get("databaseId")
            status = row.get("status")
            if db_id is None or status is None:
                print("[verify_github_action] Unexpected gh run list entry shape; polling...", file=sys.stderr)
                continue
            run_id = str(db_id)
            conclusion = row.get("conclusion") or ""
            print(f"[verify_github_action] Run {run_id}: status={status}, conclusion={conclusion}")
            if status == "completed":
                ci_passed = conclusion == "success"
                break
        else:
            print(f"[verify_github_action] Timed out after {args.timeout}s waiting for CI.")
            ci_passed = False

        if not ci_passed and run_id:
            print("[verify_github_action] CI FAILED. Fetching failed-job logs...")
            run([gh_exe, "run", "view", run_id, "--log-failed"], cwd=repo_cwd, check=False)
        elif ci_passed:
            print("[verify_github_action] CI PASSED.")

    finally:
        print(f"[verify_github_action] Cleaning up: switching back to {original_branch}...")
        run(["git", "checkout", original_branch], cwd=repo_cwd, check=False)
        run(["git", "push", args.remote, "--delete", temp_branch], cwd=repo_cwd, check=False)
        print(f"[verify_github_action] Deleted remote branch {temp_branch} (if it existed).")
        run(["git", "branch", "-D", temp_branch], cwd=repo_cwd, check=False)
        print(f"[verify_github_action] Deleted local branch {temp_branch} (if it existed).")

        if stash_pushed:
            pop2 = run(["git", "stash", "pop"], cwd=repo_cwd, check=False, capture=True)
            if pop2.returncode != 0:
                print(
                    "[verify_github_action] WARNING: final stash pop failed; try `git stash list` / `git stash pop`.\n"
                    + (pop2.stderr or ""),
                    file=sys.stderr,
                )

    if ci_passed:
        print("[verify_github_action] Done: CI is green.")
        return 0
    print("[verify_github_action] Done: CI failed or timed out.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
