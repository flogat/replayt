#!/usr/bin/env python3
"""Emit a stable JSON snapshot of [project] PEP 621 metadata from pyproject.toml."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "replayt.pyproject_pep621_report.v1"

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

# stdlib ``TOMLDecodeError`` subclasses ``ValueError``; ``tomli``'s does not on Python 3.10.
_TOML_LOAD_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    UnicodeDecodeError,
    ValueError,
    tomllib.TOMLDecodeError,
)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError("pyproject.toml root must be a table")
    return data


def _sorted_str_list(label: str, raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a TOML array of strings")
    out: list[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(f"{label}[{i}] must be a string")
        out.append(item)
    return sorted(out)


def _optional_dependency_groups(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("[project.optional-dependencies] must be a table")
    groups: dict[str, list[str]] = {}
    for name, deps in raw.items():
        if not isinstance(name, str):
            raise ValueError("optional-dependencies group names must be strings")
        groups[name] = _sorted_str_list(f"optional-dependencies[{name}]", deps)
    return dict(sorted(groups.items()))


def pyproject_pep621_report(pyproject_path: Path) -> dict[str, Any]:
    path = pyproject_path.resolve()
    if not path.is_file():
        return {
            "schema": SCHEMA,
            "ok": False,
            "path": str(path),
            "error": f"missing file: {path}",
            "project": None,
        }
    try:
        data = _load_toml(path)
    except _TOML_LOAD_ERRORS as exc:
        return {
            "schema": SCHEMA,
            "ok": False,
            "path": str(path),
            "error": str(exc),
            "project": None,
        }

    project = data.get("project")
    if not isinstance(project, dict):
        return {
            "schema": SCHEMA,
            "ok": False,
            "path": str(path),
            "error": "pyproject.toml is missing a [project] table",
            "project": None,
        }

    try:
        name = project.get("name")
        version = project.get("version")
        requires_python = project.get("requires-python")
        dependencies = _sorted_str_list("project.dependencies", project.get("dependencies"))
        optional_groups = _optional_dependency_groups(project.get("optional-dependencies"))
    except ValueError as exc:
        return {
            "schema": SCHEMA,
            "ok": False,
            "path": str(path),
            "error": str(exc),
            "project": None,
        }

    proj_out: dict[str, Any] = {
        "name": name if isinstance(name, str) else None,
        "version": version if isinstance(version, str) else None,
        "requires_python": requires_python if isinstance(requires_python, str) else None,
        "dependencies": dependencies,
        "optional_dependencies": optional_groups,
        "optional_dependency_extras": sorted(optional_groups.keys()),
    }

    return {
        "schema": SCHEMA,
        "ok": True,
        "path": str(path),
        "error": None,
        "project": proj_out,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pyproject.toml",
        help="Path to pyproject.toml (default: repository root).",
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
    report = pyproject_pep621_report(args.pyproject)

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if report["ok"]:
        proj = report["project"]
        assert isinstance(proj, dict)
        name = proj.get("name") or "(unknown)"
        ver = proj.get("version") or "(unset)"
        print(f"ok: {name} {ver} ({report['path']})")
        return 0

    print(f"error: {report['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
