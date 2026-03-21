from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path


def _load_script(module_name: str, filename: str):
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def test_public_api_report_marks_missing_declared_exports(tmp_path: Path, monkeypatch) -> None:
    pkg = tmp_path / "demo_api"
    _write(
        pkg / "__init__.py",
        """
        __version__ = "1.2.3"
        __all__ = ["visible", "missing_symbol"]

        def visible() -> str:
            return "ok"
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = _load_script("public_api_report", "public_api_report.py")

    report = mod.public_api_report("demo_api")

    assert report["schema"] == "replayt.public_api_report.v1"
    assert report["version"] == "1.2.3"
    assert report["missing_exports"] == ["missing_symbol"]
    assert report["exports"] == [
        {
            "name": "visible",
            "status": "present",
            "kind": "callable",
            "source_module": "demo_api",
        },
        {
            "name": "missing_symbol",
            "status": "missing",
            "kind": None,
            "source_module": None,
        },
    ]


def test_public_api_report_json_output_for_replayt() -> None:
    mod = _load_script("public_api_report_replayt", "public_api_report.py")

    report = mod.public_api_report()

    assert report["schema"] == "replayt.public_api_report.v1"
    assert report["module"] == "replayt"
    assert any(item["name"] == "Workflow" for item in report["exports"])


def test_docs_index_report_passes_for_complete_repo_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path / "README.md",
        """
        # demo

        ## Documentation map

        - [Docs index](docs/README.md)
        - [CLI](docs/CLI.md)
        """,
    )
    _write(
        tmp_path / "docs" / "README.md",
        """
        # Documentation

        - [CLI.md](CLI.md)
        - [SCOPE.md](SCOPE.md)
        - [architecture.mmd](architecture.mmd)
        - [Root README](../README.md)
        """,
    )
    _write(tmp_path / "docs" / "CLI.md", "# CLI\n")
    _write(tmp_path / "docs" / "SCOPE.md", "# Scope\n")
    _write(tmp_path / "docs" / "architecture.mmd", "flowchart TD\n")

    mod = _load_script("check_docs_index", "check_docs_index.py")
    report = mod.build_report(tmp_path)

    assert report["ok"] is True
    assert report["issues"] == []


def test_docs_index_report_flags_missing_doc_entry_and_broken_link(tmp_path: Path) -> None:
    _write(
        tmp_path / "README.md",
        """
        # demo

        ## Documentation map

        - [Docs index](docs/README.md)
        - [Broken](docs/MISSING.md)
        """,
    )
    _write(
        tmp_path / "docs" / "README.md",
        """
        # Documentation

        - [CLI.md](CLI.md)
        - [Root README](../README.md)
        """,
    )
    _write(tmp_path / "docs" / "CLI.md", "# CLI\n")
    _write(tmp_path / "docs" / "SCOPE.md", "# Scope\n")

    mod = _load_script("check_docs_index_bad", "check_docs_index.py")
    report = mod.build_report(tmp_path)

    assert report["ok"] is False
    assert "README.md has broken link: docs/MISSING.md" in report["issues"]
    assert "docs/README.md is missing an index entry for docs/SCOPE.md" in report["issues"]


def test_changelog_report_parses_unreleased_items() -> None:
    mod = _load_script("changelog_unreleased", "changelog_unreleased.py")
    root = Path(__file__).resolve().parents[1]

    report = mod.changelog_report(root / "CHANGELOG.md")

    assert report["ok"] is True
    assert report["item_count"] >= 1
    assert any("Maintainer release helpers" in item for item in report["items"])


def test_changelog_main_checks_nonempty(tmp_path: Path) -> None:
    _write(
        tmp_path / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        ## 0.1.0 - 2026-03-21

        - Initial release.
        """,
    )
    mod = _load_script("changelog_unreleased_empty", "changelog_unreleased.py")

    assert mod.main(["--changelog", str(tmp_path / "CHANGELOG.md"), "--check-nonempty"]) == 1


def test_version_consistency_ok_when_versions_match(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "demo"
        version = "1.0.0"
        """,
    )
    _write(
        tmp_path / "src" / "replayt" / "__init__.py",
        """
        __version__ = "1.0.0"
        """,
    )
    mod = _load_script("version_consistency_ok", "version_consistency.py")
    report = mod.version_consistency_report(tmp_path)

    assert report["schema"] == "replayt.version_consistency.v1"
    assert report["ok"] is True
    assert report["mismatch"] is False
    assert report["pyproject_version"] == "1.0.0"
    assert report["package_init_version"] == "1.0.0"


def test_version_consistency_flags_mismatch(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "demo"
        version = "2.0.0"
        """,
    )
    _write(
        tmp_path / "src" / "replayt" / "__init__.py",
        """
        __version__ = "1.9.0"
        """,
    )
    mod = _load_script("version_consistency_bad", "version_consistency.py")
    report = mod.version_consistency_report(tmp_path)

    assert report["ok"] is False
    assert report["mismatch"] is True


def test_version_consistency_replayt_repo_matches() -> None:
    mod = _load_script("version_consistency_replayt", "version_consistency.py")
    root = Path(__file__).resolve().parents[1]
    report = mod.version_consistency_report(root)
    assert report["ok"] is True, report


def test_changelog_main_json_output(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        - First note
        - Second note

        ## 0.1.0 - 2026-03-21

        - Initial release.
        """,
    )
    mod = _load_script("changelog_unreleased_json", "changelog_unreleased.py")

    exit_code = mod.main(["--changelog", str(tmp_path / "CHANGELOG.md"), "--format", "json"])

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "replayt.unreleased_changelog.v1"
    assert data["items"] == ["First note", "Second note"]
