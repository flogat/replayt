#!/usr/bin/env python3
"""Report the replayt top-level public API surface for semver reviews."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCHEMA = "replayt.public_api_report.v1"


def _ensure_repo_src_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def load_module(module_name: str) -> ModuleType:
    _ensure_repo_src_on_path()
    return importlib.import_module(module_name)


def export_names(module: ModuleType) -> list[str]:
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return [str(name) for name in declared]
    return sorted(name for name in vars(module) if not name.startswith("_"))


def export_record(module: ModuleType, name: str) -> dict[str, Any]:
    if not hasattr(module, name):
        return {
            "name": name,
            "status": "missing",
            "kind": None,
            "source_module": None,
        }

    value = getattr(module, name)
    if inspect.ismodule(value):
        kind = "module"
    elif inspect.isclass(value):
        kind = "class"
    elif inspect.isfunction(value) or inspect.ismethod(value) or inspect.isbuiltin(value):
        kind = "callable"
    else:
        kind = type(value).__name__
    return {
        "name": name,
        "status": "present",
        "kind": kind,
        "source_module": getattr(value, "__module__", module.__name__),
    }


def public_api_report(module_name: str = "replayt") -> dict[str, Any]:
    module = load_module(module_name)
    exports = [export_record(module, name) for name in export_names(module)]
    missing = [item["name"] for item in exports if item["status"] == "missing"]
    version = getattr(module, "__version__", None)
    return {
        "schema": SCHEMA,
        "module": module.__name__,
        "version": version,
        "export_count": len(exports),
        "missing_exports": missing,
        "exports": exports,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="replayt", help="Import path to inspect (default: replayt).")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = public_api_report(module_name=args.module)
    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0

    print(
        f"module={report['module']} version={report['version'] or '(unknown)'} "
        f"exports={report['export_count']} missing={len(report['missing_exports'])}"
    )
    for item in report["exports"]:
        if item["status"] == "missing":
            print(f"{item['name']}: MISSING")
            continue
        print(f"{item['name']}: {item['kind']} ({item['source_module']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
