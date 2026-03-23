#!/usr/bin/env python3
"""Extract the Unreleased section from CHANGELOG.md for release-note prep."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "replayt.unreleased_changelog.v1"
UNRELEASED_RE = re.compile(r"(?ms)^## Unreleased\s*$\n(?P<body>.*?)(?=^##\s|\Z)")


def unreleased_body(text: str) -> str | None:
    match = UNRELEASED_RE.search(text)
    if not match:
        return None
    return match.group("body").strip()


def parse_items(body: str) -> list[str]:
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


def _body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _item_sha256(item: str) -> str:
    return hashlib.sha256(item.encode("utf-8")).hexdigest()


def changelog_report(changelog_path: Path) -> dict[str, Any]:
    text = changelog_path.read_text(encoding="utf-8")
    body = unreleased_body(text)
    if body is None:
        return {
            "schema": SCHEMA,
            "path": str(changelog_path),
            "ok": False,
            "error": "CHANGELOG.md is missing a '## Unreleased' section",
            "body": None,
            "body_sha256": None,
            "items": [],
            "item_count": 0,
            "item_sha256s": [],
        }
    items = parse_items(body)
    return {
        "schema": SCHEMA,
        "path": str(changelog_path),
        "ok": True,
        "error": None,
        "body": body,
        "body_sha256": _body_sha256(body),
        "items": items,
        "item_count": len(items),
        "item_sha256s": [_item_sha256(item) for item in items],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "CHANGELOG.md",
        help="Path to CHANGELOG.md.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--check-nonempty",
        action="store_true",
        help="Exit 1 when Unreleased is missing or contains no bullet items.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = changelog_report(args.changelog)
    exit_code = 0
    if not report["ok"]:
        exit_code = 1
    elif args.check_nonempty and report["item_count"] == 0:
        exit_code = 1

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return exit_code

    if not report["ok"]:
        print(f"ERROR: {report['error']}")
        return exit_code

    print(f"unreleased_items={report['item_count']} changelog={args.changelog}")
    if report["item_count"] == 0:
        print("(no bullet items under ## Unreleased)")
    else:
        for item in report["items"]:
            print(f"- {item}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
