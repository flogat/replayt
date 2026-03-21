#!/usr/bin/env python3
"""Verify pyproject.toml [project].version matches replayt.__version__ in source."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "replayt.version_consistency.v1"

PYPROJECT_VERSION_RE = re.compile(r"^version\s*=\s*\"(?P<v>[^\"]+)\"\s*$")
INIT_VERSION_RE = re.compile(r"^__version__\s*=\s*[\"'](?P<v>[^\"']+)[\"']\s*$", re.MULTILINE)


def read_pyproject_version(pyproject_path: Path) -> tuple[str | None, str | None]:
    """Return (version, error_message)."""
    if not pyproject_path.is_file():
        return None, f"missing file: {pyproject_path}"
    text = pyproject_path.read_text(encoding="utf-8")
    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line == "[project]":
            in_project = True
            continue
        if in_project and line.startswith("[") and line.endswith("]"):
            break
        if in_project and line.startswith("version"):
            match = PYPROJECT_VERSION_RE.match(line)
            if match:
                return match.group("v"), None
            return None, f"unparseable version line in [project]: {line!r}"
    return None, "no version = \"...\" line found in [project] section"


def read_package_init_version(init_path: Path) -> tuple[str | None, str | None]:
    if not init_path.is_file():
        return None, f"missing file: {init_path}"
    text = init_path.read_text(encoding="utf-8")
    match = INIT_VERSION_RE.search(text)
    if not match:
        return None, f"no __version__ assignment found in {init_path}"
    return match.group("v"), None


def version_consistency_report(repo_root: Path) -> dict[str, Any]:
    pyproject_path = repo_root / "pyproject.toml"
    init_path = repo_root / "src" / "replayt" / "__init__.py"

    py_ver, py_err = read_pyproject_version(pyproject_path)
    init_ver, init_err = read_package_init_version(init_path)

    errors: list[str] = []
    if py_err:
        errors.append(py_err)
    if init_err:
        errors.append(init_err)

    mismatch = bool(py_ver and init_ver and py_ver != init_ver)
    ok = not errors and py_ver is not None and init_ver is not None and py_ver == init_ver

    return {
        "schema": SCHEMA,
        "ok": ok,
        "pyproject_path": str(pyproject_path),
        "package_init_path": str(init_path),
        "pyproject_version": py_ver,
        "package_init_version": init_ver,
        "mismatch": mismatch,
        "errors": errors,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: parent of this script).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = version_consistency_report(args.repo.resolve())

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if report["ok"]:
        print(f"ok: version {report['pyproject_version']} (pyproject.toml and package __init__ match)")
        return 0

    for msg in report["errors"]:
        print(f"error: {msg}", file=sys.stderr)
    if report["mismatch"]:
        print(
            f"error: version mismatch pyproject={report['pyproject_version']!r} "
            f"__init__={report['package_init_version']!r}",
            file=sys.stderr,
        )
    elif not report["errors"]:
        print("error: versions could not be compared", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
