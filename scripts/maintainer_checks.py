#!/usr/bin/env python3
"""Run maintainer-facing repo checks in one shot (version, changelog, docs, example catalog, public API)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "replayt.maintainer_checks.v1"

_LOADED: dict[str, Any] = {}


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_script(unique: str, filename: str) -> Any:
    if filename in _LOADED:
        return _LOADED[filename]
    path = _scripts_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"maintainer helper script not found: {path}")
    spec = importlib.util.spec_from_file_location(f"_replayt_maintainer_{unique}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load maintainer helper script: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LOADED[filename] = mod
    return mod


def maintainer_checks_report(
    repo_root: Path,
    *,
    changelog_nonempty: bool = False,
    skip_version: bool = False,
    skip_changelog: bool = False,
    skip_docs_index: bool = False,
    skip_pyproject_pep621: bool = False,
    skip_changelog_gate_policy: bool = False,
    skip_example_catalog: bool = False,
    skip_public_api: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    changelog_path = repo_root / "CHANGELOG.md"
    example_catalog_snapshot = repo_root / "docs" / "EXAMPLE_CATALOG_CONTRACT.json"
    public_api_snapshot = repo_root / "docs" / "PUBLIC_API_CONTRACT.json"

    checks: dict[str, Any] = {}
    details: dict[str, Any] = {}
    errors: list[str] = []

    if not skip_version:
        vc = _load_script("vc", "version_consistency.py")
        vr = vc.version_consistency_report(repo_root)
        checks["version_consistency"] = {"ok": bool(vr["ok"]), "schema": vr["schema"]}
        if verbose:
            details["version_consistency"] = vr
        if not vr["ok"]:
            errors.append("version_consistency failed (pyproject vs package __version__)")

    if not skip_pyproject_pep621:
        pp = _load_script("pp", "pyproject_pep621_report.py")
        pr = pp.pyproject_pep621_report(repo_root / "pyproject.toml")
        checks["pyproject_pep621"] = {"ok": bool(pr["ok"]), "schema": pr["schema"]}
        if verbose:
            details["pyproject_pep621"] = pr
        if not pr["ok"]:
            errors.append("pyproject_pep621 failed (parse error or missing [project])")

    if not skip_changelog_gate_policy:
        cgp = _load_script("cgp", "changelog_gate_policy.py")
        gr = cgp.changelog_gate_policy_report()
        checks["changelog_gate_policy"] = {"ok": True, "schema": gr["schema"]}
        if verbose:
            details["changelog_gate_policy"] = gr

    if not skip_changelog:
        cl = _load_script("cl", "changelog_unreleased.py")
        cr = cl.changelog_report(changelog_path)
        changelog_ok = bool(cr.get("ok"))
        if changelog_nonempty:
            changelog_ok = changelog_ok and cr.get("item_count", 0) > 0
        checks["changelog_unreleased"] = {
            "ok": changelog_ok,
            "schema": cr.get("schema"),
            "item_count": cr.get("item_count", 0),
        }
        if verbose:
            details["changelog_unreleased"] = cr
        if not changelog_ok:
            if not cr.get("ok"):
                errors.append("changelog_unreleased failed (missing ## Unreleased or parse error)")
            else:
                errors.append("changelog_unreleased failed (--changelog-nonempty: no bullet items)")

    if not skip_docs_index:
        di = _load_script("di", "check_docs_index.py")
        dr = di.build_report(repo_root)
        checks["docs_index"] = {"ok": bool(dr["ok"]), "schema": dr["schema"]}
        if verbose:
            details["docs_index"] = dr
        if not dr["ok"]:
            errors.append("docs_index failed (README map or docs/README.md index)")

    if not skip_example_catalog:
        ec = _load_script("ec", "example_catalog_contract.py")
        er = ec.check_snapshot(
            example_catalog_snapshot,
            module_name="replayt_examples",
            repo_root=repo_root,
        )
        checks["example_catalog"] = {
            "ok": bool(er["ok"]),
            "schema": er["schema"],
            "snapshot_path": er["snapshot_path"],
            "error_count": len(er.get("errors") or []),
        }
        if verbose:
            details["example_catalog"] = er
        if not er["ok"]:
            errors.append("example_catalog failed (packaged example contract drift)")

    if not skip_public_api:
        api = _load_script("api", "public_api_report.py")
        ar = api.check_snapshot(
            public_api_snapshot,
            module_name="replayt",
            repo_root=repo_root,
        )
        api_ok = bool(ar["ok"])
        checks["public_api"] = {
            "ok": api_ok,
            "schema": ar["schema"],
            "snapshot_path": ar["snapshot_path"],
            "missing_export_count": len(ar.get("missing_exports") or []),
            "diff_line_count": len(ar.get("diff") or []),
        }
        if verbose:
            details["public_api"] = ar
        if not api_ok:
            errors.append("public_api failed (contract snapshot drift or missing exports)")

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "repo_root": str(repo_root),
        "ok": len(errors) == 0,
        "changelog_nonempty_required": changelog_nonempty,
        "checks": checks,
        "errors": errors,
    }
    if verbose and details:
        out["details"] = details
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: parent of scripts/).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--changelog-nonempty",
        action="store_true",
        help="Require at least one bullet under ## Unreleased (release-prep mode).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include full sub-reports under 'details' in JSON output.",
    )
    parser.add_argument("--skip-version", action="store_true", help="Skip pyproject vs __version__ check.")
    parser.add_argument(
        "--skip-pyproject-pep621",
        action="store_true",
        help="Skip [project] PEP 621 metadata parse report.",
    )
    parser.add_argument(
        "--skip-changelog-gate-policy",
        action="store_true",
        help="Skip machine-readable PR changelog gate policy report.",
    )
    parser.add_argument("--skip-changelog", action="store_true", help="Skip Unreleased changelog check.")
    parser.add_argument("--skip-docs-index", action="store_true", help="Skip docs/README.md index check.")
    parser.add_argument(
        "--skip-example-catalog",
        action="store_true",
        help="Skip replayt_examples packaged-catalog contract snapshot check.",
    )
    parser.add_argument(
        "--skip-public-api",
        action="store_true",
        help="Skip replayt __all__ / export surface check (for partial trees).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = maintainer_checks_report(
        args.repo,
        changelog_nonempty=args.changelog_nonempty,
        skip_version=args.skip_version,
        skip_changelog=args.skip_changelog,
        skip_docs_index=args.skip_docs_index,
        skip_pyproject_pep621=args.skip_pyproject_pep621,
        skip_changelog_gate_policy=args.skip_changelog_gate_policy,
        skip_example_catalog=args.skip_example_catalog,
        skip_public_api=args.skip_public_api,
        verbose=args.verbose,
    )

    if not report["checks"]:
        msg = "ERROR: all checks skipped (remove at least one --skip-* flag)"
        if args.format == "json":
            print(json.dumps({**report, "ok": False, "errors": [msg]}, indent=2))
        else:
            print(msg, file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    enabled = [name for name, body in report["checks"].items() if body is not None]
    total = len(enabled)
    passed = sum(1 for body in report["checks"].values() if body.get("ok"))
    if report["ok"]:
        print(f"OK: maintainer checks ({passed}/{total} passed, repo={report['repo_root']})")
        return 0

    print(f"ERROR: maintainer checks ({passed}/{total} passed, repo={report['repo_root']})")
    for err in report["errors"]:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
