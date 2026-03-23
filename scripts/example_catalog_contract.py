#!/usr/bin/env python3
"""Snapshot the packaged replayt_examples catalog for semver and docs reviews."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "replayt.example_catalog_contract.v1"
CHECK_SCHEMA = "replayt.example_catalog_contract_check.v1"


def _example_row_sha256(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_repo_src_on_path(repo_root: Path | None = None) -> None:
    root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
    src = root / "src"
    src_str = str(src)
    sys.path[:] = [entry for entry in sys.path if entry != src_str]
    sys.path.insert(0, src_str)


def load_module(module_name: str, *, repo_root: Path | None = None) -> Any:
    resolved_root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
    _ensure_repo_src_on_path(resolved_root)
    prefix = f"{module_name}."
    for name in [name for name in sys.modules if name == module_name or name.startswith(prefix)]:
        del sys.modules[name]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def example_catalog_contract_report(
    module_name: str = "replayt_examples",
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    module = load_module(module_name, repo_root=repo_root)
    list_fn = getattr(module, "list_packaged_examples", None)
    if not callable(list_fn):
        raise RuntimeError(f"{module_name!r} does not expose callable list_packaged_examples()")
    examples = []
    for spec in list_fn():
        examples.append(
            {
                "key": str(spec.key),
                "title": str(spec.title),
                "target": str(spec.target),
                "description": str(spec.description),
                "llm_backed": bool(spec.llm_backed),
                "inputs_example": spec.inputs_example,
            }
        )
    return {
        "schema": SCHEMA,
        "module": module.__name__,
        "example_count": len(examples),
        "examples": examples,
        "example_sha256s": [_example_row_sha256(row) for row in examples],
    }


def write_snapshot(report: dict[str, Any], snapshot_path: Path) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_snapshot(
    snapshot_path: Path,
    *,
    module_name: str = "replayt_examples",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    current = example_catalog_contract_report(module_name=module_name, repo_root=repo_root)
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

    ok = not errors and expected == current
    if not ok and isinstance(expected, dict):
        expected_text = json.dumps(expected, indent=2, sort_keys=True).splitlines()
        current_text = json.dumps(current, indent=2, sort_keys=True).splitlines()
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
        "example_count": current["example_count"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root whose src/ contains the packaged examples.",
    )
    parser.add_argument(
        "--module",
        default="replayt_examples",
        help="Import path that exposes list_packaged_examples() (default: replayt_examples).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--snapshot-out",
        type=Path,
        help="Write the current contract JSON to this path.",
    )
    parser.add_argument(
        "--check",
        type=Path,
        help="Compare the current contract to a checked-in JSON snapshot.",
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
                    f"OK: example catalog matches {report['snapshot_path']} "
                    f"({report['example_count']} examples)"
                )
            else:
                print(f"ERROR: example catalog drift ({report['snapshot_path']})")
                for err in report["errors"]:
                    print(f"- {err}")
                for line in report["diff"]:
                    print(line)
        return 0 if report["ok"] else 1

    report = example_catalog_contract_report(module_name=args.module, repo_root=args.repo)
    if args.snapshot_out is not None:
        write_snapshot(report, args.snapshot_out)
    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0

    print(f"module={report['module']} examples={report['example_count']}")
    for item in report["examples"]:
        mode = "llm-backed" if item["llm_backed"] else "deterministic"
        print(f"{item['key']}: {item['target']} [{mode}]")
    if args.snapshot_out is not None:
        print(f"snapshot_written={args.snapshot_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
