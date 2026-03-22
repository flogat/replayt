#!/usr/bin/env python3
"""Verify that the current working tree changes pass GitHub Actions CI.

Uses ``git stash`` so that after the temp branch is deleted, the original uncommitted
working tree (including edits from the skill loop) is restored. A naive
``checkout main`` + ``reset --soft`` sequence drops those edits and can rewind the
wrong commit.

Requirements: git. For remote workflow verification, ``gh`` must be on PATH (authenticated);
if it is missing, the script skips and exits 0 unless ``--require-gh`` is set. ``ci.yml``
should include ``workflow_dispatch``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time


def resolve_gh_executable() -> str | None:
    """Return a path to ``gh`` suitable for ``subprocess``, or None if not on PATH."""
    return shutil.which("gh")


def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    kwargs: dict = {"check": check}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def run_out(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify GitHub Actions CI before releasing.")
    parser.add_argument("--workflow", default="ci.yml", help="Workflow file to trigger (default: ci.yml).")
    parser.add_argument("--remote", default="origin", help="Git remote (default: origin).")
    parser.add_argument("--poll-interval", type=float, default=20.0, help="Poll interval seconds (default: 20).")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Max wait seconds (default: 1800).")
    parser.add_argument(
        "--require-gh",
        action="store_true",
        help="Exit with code 1 if the GitHub CLI (gh) is not on PATH (default: skip verification and exit 0).",
    )
    args = parser.parse_args(argv)

    gh_exe = resolve_gh_executable()
    if gh_exe is None:
        msg = (
            "[verify_github_action] GitHub CLI (gh) not found on PATH; cannot trigger or poll workflow runs. "
            "Install https://cli.github.com/ or add gh to PATH."
        )
        if args.require_gh:
            print(msg, file=sys.stderr)
            return 1
        print(f"{msg} Skipping verification (exit 0). Use --require-gh to fail instead.")
        return 0

    original_branch = run_out(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    timestamp = int(time.time())
    temp_branch = f"tmp-ci-verify-{timestamp}"
    stash_message = f"replayt-verify-ci-{timestamp}"

    dirty = run_out(["git", "status", "--porcelain"])
    has_staged = bool(run_out(["git", "diff", "--cached", "--name-only"]))
    has_wip = bool(dirty) or has_staged

    print(f"[verify_github_action] Original branch: {original_branch}")
    print(f"[verify_github_action] Temp branch: {temp_branch}")

    stash_pushed = False
    if has_wip:
        run(["git", "stash", "push", "-u", "-m", stash_message])
        stash_pushed = True
        print("[verify_github_action] Stashed working tree (including untracked) for CI branch.")

    ci_passed = False
    run_id: str | None = None

    try:
        run(["git", "checkout", "-b", temp_branch])
        if stash_pushed:
            applied = run(["git", "stash", "apply"], check=False, capture=True)
            if applied.returncode != 0:
                print(
                    "[verify_github_action] ERROR: git stash apply failed; resolve conflicts, then retry.\n"
                    + (applied.stderr or ""),
                    file=sys.stderr,
                )
                return 1
            run(["git", "add", "-A"])
            run(["git", "commit", "-m", f"temp: ci verify {timestamp}"])

        run(["git", "push", "-u", args.remote, temp_branch])
        print(f"[verify_github_action] Pushed temp branch {temp_branch} to {args.remote}.")

        result = run(
            [gh_exe, "workflow", "run", args.workflow, "--ref", temp_branch],
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
                check=False,
                capture=True,
            )
            if list_result.returncode != 0 or not list_result.stdout.strip() or list_result.stdout.strip() == "[]":
                print("[verify_github_action] No runs found yet, polling...")
                continue
            runs = json.loads(list_result.stdout)
            if not runs:
                print("[verify_github_action] No runs found yet, polling...")
                continue
            run_id = str(runs[0]["databaseId"])
            status = runs[0]["status"]
            conclusion = runs[0].get("conclusion") or ""
            print(f"[verify_github_action] Run {run_id}: status={status}, conclusion={conclusion}")
            if status == "completed":
                ci_passed = conclusion == "success"
                break
        else:
            print(f"[verify_github_action] Timed out after {args.timeout}s waiting for CI.")
            ci_passed = False

        if not ci_passed and run_id:
            print("[verify_github_action] CI FAILED. Fetching failed-job logs...")
            run([gh_exe, "run", "view", run_id, "--log-failed"], check=False)
        elif ci_passed:
            print("[verify_github_action] CI PASSED.")

    finally:
        print(f"[verify_github_action] Cleaning up: switching back to {original_branch}...")
        run(["git", "checkout", original_branch], check=False)
        run(["git", "push", args.remote, "--delete", temp_branch], check=False)
        print(f"[verify_github_action] Deleted remote branch {temp_branch} (if it existed).")
        run(["git", "branch", "-D", temp_branch], check=False)
        print(f"[verify_github_action] Deleted local branch {temp_branch} (if it existed).")

        if stash_pushed:
            pop2 = run(["git", "stash", "pop"], check=False, capture=True)
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
