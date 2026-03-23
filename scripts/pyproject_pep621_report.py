#!/usr/bin/env python3
"""Emit a stable JSON snapshot of [project] PEP 621 metadata from pyproject.toml."""

from __future__ import annotations

import argparse
import hashlib
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


def _optional_str(label: str, raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string")
    return raw


def _normalize_readme(raw: Any) -> tuple[str | None, str | None, str | None]:
    """Return (readme_file, readme_content_type, readme_text_sha256 for inline text only)."""
    if raw is None:
        return None, None, None
    if isinstance(raw, str):
        return raw, None, None
    if not isinstance(raw, dict):
        raise ValueError("project.readme must be a string or an inline table")
    ct_raw = raw.get("content-type", raw.get("content_type"))
    content_type = ct_raw if isinstance(ct_raw, str) else None
    if "file" in raw:
        f = raw.get("file")
        if not isinstance(f, str):
            raise ValueError("project.readme.file must be a string")
        return f, content_type, None
    if "text" in raw:
        t = raw.get("text")
        if not isinstance(t, str):
            raise ValueError("project.readme.text must be a string")
        digest = hashlib.sha256(t.encode("utf-8")).hexdigest()
        return None, content_type, digest
    raise ValueError("project.readme table must set file or text")


def _normalize_license(raw: Any) -> tuple[str | None, str | None, str | None]:
    """Return (SPDX expression, license file path, sha256 of inline license text)."""
    if raw is None:
        return None, None, None
    if isinstance(raw, str):
        return raw, None, None
    if not isinstance(raw, dict):
        raise ValueError("project.license must be a string or an inline table")
    if "file" in raw:
        f = raw.get("file")
        if not isinstance(f, str):
            raise ValueError("project.license.file must be a string")
        return None, f, None
    if "text" in raw:
        t = raw.get("text")
        if not isinstance(t, str):
            raise ValueError("project.license.text must be a string")
        return None, None, hashlib.sha256(t.encode("utf-8")).hexdigest()
    raise ValueError("project.license table must set file or text")


def _person_tables(label: str, raw: Any) -> list[dict[str, str | None]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a TOML array of inline tables")
    rows: list[dict[str, str | None]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{i}] must be an inline table")
        name = item.get("name")
        email = item.get("email")
        if name is not None and not isinstance(name, str):
            raise ValueError(f"{label}[{i}].name must be a string")
        if email is not None and not isinstance(email, str):
            raise ValueError(f"{label}[{i}].email must be a string")
        rows.append({"name": name, "email": email})
    rows.sort(key=lambda r: ((r["name"] or ""), (r["email"] or "")))
    return rows


def _sorted_url_table(label: str, raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a table")
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(f"{label} keys and values must be strings")
        out[k] = v
    return dict(sorted(out.items()))


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
        description = _optional_str("project.description", project.get("description"))
        readme_file, readme_content_type, readme_text_sha256 = _normalize_readme(project.get("readme"))
        license_expression, license_file, license_text_sha256 = _normalize_license(project.get("license"))
        keywords = _sorted_str_list("project.keywords", project.get("keywords"))
        classifiers = _sorted_str_list("project.classifiers", project.get("classifiers"))
        urls = _sorted_url_table("project.urls", project.get("urls"))
        authors = _person_tables("project.authors", project.get("authors"))
        maintainers = _person_tables("project.maintainers", project.get("maintainers"))
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
        "description": description,
        "readme_file": readme_file,
        "readme_content_type": readme_content_type,
        "readme_text_sha256": readme_text_sha256,
        "license_expression": license_expression,
        "license_file": license_file,
        "license_text_sha256": license_text_sha256,
        "requires_python": requires_python if isinstance(requires_python, str) else None,
        "keywords": keywords,
        "classifiers": classifiers,
        "urls": urls,
        "authors": authors,
        "maintainers": maintainers,
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
