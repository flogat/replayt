#!/usr/bin/env python3
"""Verify the docs index and README documentation map stay in sync with local files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "replayt.docs_index_report.v1"
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def markdown_links(text: str) -> list[str]:
    return [match.group(1).strip() for match in _LINK_RE.finditer(text)]


def _local_link_target(file_path: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target:
        return None
    return (file_path.parent / target).resolve()


def _broken_links(file_path: Path, repo_root: Path) -> list[str]:
    issues: list[str] = []
    text = file_path.read_text(encoding="utf-8")
    for raw_target in markdown_links(text):
        target = _local_link_target(file_path, raw_target)
        if target is None:
            continue
        try:
            target.relative_to(repo_root.resolve())
        except ValueError:
            issues.append(f"{file_path.relative_to(repo_root)} links outside repo: {raw_target}")
            continue
        if not target.exists():
            issues.append(f"{file_path.relative_to(repo_root)} has broken link: {raw_target}")
    return issues


def expected_docs_targets(repo_root: Path) -> set[Path]:
    docs_dir = repo_root / "docs"
    expected = {path.resolve() for path in docs_dir.glob("*.md") if path.name != "README.md"}
    architecture = docs_dir / "architecture.mmd"
    if architecture.exists():
        expected.add(architecture.resolve())
    return expected


def docs_index_targets(repo_root: Path) -> set[Path]:
    index_path = repo_root / "docs" / "README.md"
    targets: set[Path] = set()
    for raw_target in markdown_links(index_path.read_text(encoding="utf-8")):
        target = _local_link_target(index_path, raw_target)
        if target is None:
            continue
        try:
            target.relative_to((repo_root / "docs").resolve())
        except ValueError:
            continue
        targets.add(target)
    return targets


def build_report(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    index_path = repo_root / "docs" / "README.md"
    readme_path = repo_root / "README.md"
    issues = _broken_links(index_path, repo_root) + _broken_links(readme_path, repo_root)

    expected = expected_docs_targets(repo_root)
    indexed = docs_index_targets(repo_root)
    missing = sorted(path.relative_to(repo_root).as_posix() for path in expected - indexed)
    for path in missing:
        issues.append(f"docs/README.md is missing an index entry for {path}")

    return {
        "schema": SCHEMA,
        "repo_root": str(repo_root),
        "ok": not issues,
        "checked_files": ["README.md", "docs/README.md"],
        "expected_docs_targets": sorted(path.relative_to(repo_root).as_posix() for path in expected),
        "indexed_docs_targets": sorted(path.relative_to(repo_root).as_posix() for path in indexed),
        "issues": issues,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1], help="Repository root.")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.repo)
    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if report["ok"]:
        print(
            "OK: docs/README.md covers every top-level docs file, and README.md / docs/README.md links resolve."
        )
        return 0

    print("ERROR: docs index check failed:")
    for issue in report["issues"]:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
