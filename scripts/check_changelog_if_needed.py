#!/usr/bin/env python3
"""On GitHub pull requests, require CHANGELOG.md to change when protected paths change."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def is_protected_path(path: str) -> bool:
    if path == "docs/RUN_LOG_SCHEMA.md":
        return True
    return path.startswith("src/replayt/") or path.startswith("src/replayt_examples/")


def _git_command(repo: Path, *args: str) -> list[str]:
    return ["git", "-c", f"safe.directory={repo.resolve()}", *args]


def changed_files_vs_base(base_branch: str) -> list[str]:
    repo = Path.cwd()
    # Shallow fetch so origin/<base> exists in PR jobs.
    subprocess.run(
        _git_command(repo, "fetch", "--depth=256", "origin", base_branch),
        check=False,
        capture_output=True,
    )
    result = subprocess.run(
        _git_command(repo, "diff", "--name-only", f"origin/{base_branch}...HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def need_changelog_update(files: list[str]) -> bool:
    protected = any(is_protected_path(p) for p in files)
    if not protected:
        return False
    return "CHANGELOG.md" not in files


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME", "") != "pull_request":
        return 0
    base = os.environ.get("GITHUB_BASE_REF", "main")
    try:
        files = changed_files_vs_base(base)
    except subprocess.CalledProcessError as exc:
        print(f"check_changelog_if_needed: git diff failed: {exc}", file=sys.stderr)
        return 1
    if not need_changelog_update(files):
        return 0
    preview = files[:25]
    more = " ..." if len(files) > 25 else ""
    print(
        "ERROR: Protected paths changed but CHANGELOG.md was not modified in this branch.\n"
        "Add a user-facing bullet under the next version (or Unreleased) in CHANGELOG.md.\n"
        f"Changed files ({len(files)}): {preview}{more}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
