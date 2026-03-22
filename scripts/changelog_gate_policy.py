#!/usr/bin/env python3
"""Machine-readable rules for when CI requires CHANGELOG.md on pull requests."""

from __future__ import annotations

import argparse
import json
from typing import Any

SCHEMA = "replayt.changelog_gate_policy.v1"

# Keep in sync with scripts/check_changelog_if_needed.py (imported from here).
_EXACT_PATHS: frozenset[str] = frozenset({"docs/RUN_LOG_SCHEMA.md"})
_PATH_PREFIXES: tuple[str, ...] = ("src/replayt/", "src/replayt_examples/")


def is_protected_path(path: str) -> bool:
    if path in _EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PATH_PREFIXES)


def changelog_gate_policy_report() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "exact_paths": sorted(_EXACT_PATHS),
        "path_prefixes": sorted(_PATH_PREFIXES),
        "github_actions_script": "scripts/check_changelog_if_needed.py",
        "notes": (
            "When GITHUB_EVENT_NAME is pull_request, any changed file matching "
            "exact_paths or path_prefixes requires CHANGELOG.md in the same diff."
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = changelog_gate_policy_report()
    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0
    print("replayt PR changelog gate (paths that require CHANGELOG.md when changed)")
    for label, items in (
        ("exact_paths", report["exact_paths"]),
        ("path_prefixes", report["path_prefixes"]),
    ):
        print(f"{label}:")
        for item in items:
            print(f"  - {item}")
    print(f"github_actions_script: {report['github_actions_script']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
