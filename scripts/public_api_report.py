#!/usr/bin/env python3
"""Report the replayt top-level public API surface for semver reviews."""

from __future__ import annotations

import argparse
import difflib
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCHEMA = "replayt.public_api_report.v1"
CHECK_SCHEMA = "replayt.public_api_report_check.v1"


def _ensure_repo_src_on_path(repo_root: Path | None = None) -> None:
    root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
    src = root / "src"
    src_str = str(src)
    sys.path[:] = [entry for entry in sys.path if entry != src_str]
    sys.path.insert(0, src_str)


def load_module(module_name: str, *, repo_root: Path | None = None) -> ModuleType:
    _ensure_repo_src_on_path(repo_root)
    importlib.invalidate_caches()
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return importlib.reload(existing)
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


def _snapshot_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "module": report["module"],
        "export_count": report["export_count"],
        "missing_exports": report["missing_exports"],
        "exports": report["exports"],
    }


def public_api_report(
    module_name: str = "replayt",
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    module = load_module(module_name, repo_root=repo_root)
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


def write_snapshot(report: dict[str, Any], snapshot_path: Path) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(_snapshot_payload(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check_snapshot(
    snapshot_path: Path,
    *,
    module_name: str = "replayt",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    current = public_api_report(module_name=module_name, repo_root=repo_root)
    current_snapshot = _snapshot_payload(current)
    errors: list[str] = []
    diff: list[str] = []
    snapshot_path = snapshot_path.resolve()
    try:
        expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"snapshot file not found: {snapshot_path}")
        expected = None
    except json.JSONDecodeError as exc:
        errors.append(f"snapshot is not valid JSON: {snapshot_path} ({exc})")
        expected = None

    if isinstance(expected, dict) and expected.get("schema") != SCHEMA:
        errors.append(
            f"snapshot schema mismatch: expected {SCHEMA}, found {expected.get('schema')!r}"
        )

    ok = not errors and expected == current_snapshot
    if not ok and isinstance(expected, dict):
        expected_text = json.dumps(expected, indent=2, sort_keys=True).splitlines()
        current_text = json.dumps(current_snapshot, indent=2, sort_keys=True).splitlines()
        diff = list(
            difflib.unified_diff(
                expected_text,
                current_text,
                fromfile=str(snapshot_path),
                tofile=f"live:{module_name}",
                lineterm="",
            )
        )

    return {
        "schema": CHECK_SCHEMA,
        "ok": ok,
        "module": module_name,
        "snapshot_path": str(snapshot_path),
        "errors": errors,
        "diff": diff,
        "current_schema": current["schema"],
        "current_version": current["version"],
        "export_count": current["export_count"],
        "missing_exports": current["missing_exports"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root whose src/ contains the inspected module.",
    )
    parser.add_argument("--module", default="replayt", help="Import path to inspect (default: replayt).")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--snapshot-out",
        type=Path,
        help="Write the current public API contract JSON to this path.",
    )
    parser.add_argument(
        "--check",
        type=Path,
        help="Compare the current public API contract to a checked-in JSON snapshot.",
    )
    args = parser.parse_args(argv)
    if args.snapshot_out is not None and args.check is not None:
        parser.error("Cannot combine --snapshot-out with --check")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check is not None:
        report = check_snapshot(args.check, module_name=args.module, repo_root=args.repo)
        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            if report["ok"]:
                print(
                    f"OK: public API contract matches {report['snapshot_path']} "
                    f"({report['export_count']} exports)"
                )
            else:
                print(f"ERROR: public API contract drift ({report['snapshot_path']})")
                for err in report["errors"]:
                    print(f"- {err}")
                for line in report["diff"]:
                    print(line)
        return 0 if report["ok"] else 1

    report = public_api_report(module_name=args.module, repo_root=args.repo)
    if args.snapshot_out is not None:
        write_snapshot(report, args.snapshot_out)
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
    if args.snapshot_out is not None:
        print(f"snapshot_written={args.snapshot_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
