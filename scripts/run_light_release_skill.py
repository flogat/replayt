#!/usr/bin/env python3
"""Skill runner for ``--light`` smoke runs: fast ``dummy_changelog``; ``fix_check`` delegates to Codex."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _apply_dummy_changelog(repo: Path) -> None:
    changelog = repo / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    note = "- Dummy changelog entry for testing the release loop."
    if note in text:
        return
    marker = "## Unreleased\n\n"
    if marker not in text:
        raise SystemExit("CHANGELOG.md: expected '## Unreleased' header with blank line after it")
    changelog.write_text(text.replace(marker, marker + note + "\n", 1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True)
    args = parser.parse_args(argv)

    repo = Path(os.environ["REPO_ROOT"]).resolve()
    skill = os.environ.get("SKILL_NAME", "")
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "run_codex_skill.py"
    prompt = Path(args.prompt_file).resolve()

    if skill == "dummy_changelog":
        _apply_dummy_changelog(repo)
        return 0

    return subprocess.call(
        [sys.executable, str(runner), "--prompt-file", str(prompt)],
        cwd=str(repo),
        env=os.environ,
    )


if __name__ == "__main__":
    raise SystemExit(main())
