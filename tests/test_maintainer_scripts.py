from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest


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


def test_example_catalog_contract_report_for_temp_module(tmp_path: Path, monkeypatch) -> None:
    pkg = tmp_path / "demo_examples"
    _write(
        pkg / "__init__.py",
        """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class ExampleSpec:
            key: str
            title: str
            target: str
            description: str
            inputs_example: dict
            llm_backed: bool = False

        def list_packaged_examples():
            return [
                ExampleSpec(
                    key="hello",
                    title="Hello",
                    target="demo_examples.hello:wf",
                    description="A tiny example.",
                    inputs_example={"name": "Sam"},
                    llm_backed=False,
                )
            ]
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = _load_script("example_catalog_contract_tmp", "example_catalog_contract.py")

    report = mod.example_catalog_contract_report("demo_examples")

    assert report["schema"] == "replayt.example_catalog_contract.v1"
    assert report["module"] == "demo_examples"
    assert report["example_count"] == 1
    assert report["examples"] == [
        {
            "key": "hello",
            "title": "Hello",
            "target": "demo_examples.hello:wf",
            "description": "A tiny example.",
            "llm_backed": False,
            "inputs_example": {"name": "Sam"},
        }
    ]


def test_example_catalog_contract_check_snapshot_round_trip(tmp_path: Path) -> None:
    mod = _load_script("example_catalog_contract_roundtrip", "example_catalog_contract.py")
    snapshot = tmp_path / "example_catalog.json"
    report = mod.example_catalog_contract_report()
    mod.write_snapshot(report, snapshot)

    check = mod.check_snapshot(snapshot)

    assert check["schema"] == "replayt.example_catalog_contract_check.v1"
    assert check["ok"] is True
    assert check["errors"] == []
    assert check["diff"] == []


def test_example_catalog_contract_check_flags_drift(tmp_path: Path) -> None:
    mod = _load_script("example_catalog_contract_drift", "example_catalog_contract.py")
    snapshot = tmp_path / "example_catalog.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema": "replayt.example_catalog_contract.v1",
                "module": "replayt_examples",
                "example_count": 1,
                "examples": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    check = mod.check_snapshot(snapshot)

    assert check["ok"] is False
    assert check["errors"] == []
    assert any(line.startswith("--- ") for line in check["diff"])


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


def test_changelog_report_parses_unreleased_items(tmp_path: Path) -> None:
    _write(
        tmp_path / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        - **Maintainer release helpers:** added a thing.
        - Second item.

        ## 0.1.0 - 2026-03-21
        """
    )
    mod = _load_script("changelog_unreleased", "changelog_unreleased.py")

    report = mod.changelog_report(tmp_path / "CHANGELOG.md")

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


def test_maintainer_checks_tmp_pass_skipping_public_api(tmp_path: Path) -> None:
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
    _write(
        tmp_path / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        - Note one.

        ## 0.1.0 - 2026-03-21

        - Initial release.
        """,
    )
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
    _write(
        tmp_path / "src" / "replayt_examples" / "__init__.py",
        """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class ExampleSpec:
            key: str
            title: str
            target: str
            description: str
            inputs_example: dict
            llm_backed: bool = False

        def list_packaged_examples():
            return [
                ExampleSpec(
                    key="hello",
                    title="Hello",
                    target="replayt_examples.hello:wf",
                    description="A tiny example.",
                    inputs_example={"name": "Sam"},
                )
            ]
        """,
    )
    _write(
        tmp_path / "docs" / "EXAMPLE_CATALOG_CONTRACT.json",
        """
        {
          "example_count": 1,
          "examples": [
            {
              "description": "A tiny example.",
              "inputs_example": {
                "name": "Sam"
              },
              "key": "hello",
              "llm_backed": false,
              "target": "replayt_examples.hello:wf",
              "title": "Hello"
            }
          ],
          "module": "replayt_examples",
          "schema": "replayt.example_catalog_contract.v1"
        }
        """,
    )

    mod = _load_script("maintainer_checks_tmp", "maintainer_checks.py")
    report = mod.maintainer_checks_report(tmp_path, skip_public_api=True)

    assert report["schema"] == "replayt.maintainer_checks.v1"
    assert report["ok"] is True
    assert report["checks"]["version_consistency"]["ok"] is True
    assert report["checks"]["changelog_unreleased"]["ok"] is True
    assert report["checks"]["docs_index"]["ok"] is True
    assert report["checks"]["example_catalog"]["ok"] is True


def test_maintainer_checks_version_only_failure(tmp_path: Path) -> None:
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
        __version__ = "1.0.0"
        """,
    )
    mod = _load_script("maintainer_checks_ver", "maintainer_checks.py")
    report = mod.maintainer_checks_report(
        tmp_path,
        skip_changelog=True,
        skip_docs_index=True,
        skip_example_catalog=True,
        skip_public_api=True,
    )

    assert report["ok"] is False
    assert "version_consistency" in report["checks"]
    assert report["checks"]["version_consistency"]["ok"] is False


def test_maintainer_checks_changelog_nonempty_fails_on_empty_bullets(tmp_path: Path) -> None:
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
    _write(
        tmp_path / "CHANGELOG.md",
        """
        # Changelog

        ## Unreleased

        ## 0.1.0 - 2026-03-21

        - Initial release.
        """,
    )
    mod = _load_script("maintainer_checks_cl", "maintainer_checks.py")
    report = mod.maintainer_checks_report(
        tmp_path,
        changelog_nonempty=True,
        skip_docs_index=True,
        skip_example_catalog=True,
        skip_public_api=True,
    )

    assert report["ok"] is False
    assert report["checks"]["changelog_unreleased"]["ok"] is False
    assert report["checks"]["changelog_unreleased"]["item_count"] == 0


def test_maintainer_checks_main_all_skips_exits_2(capsys) -> None:
    mod = _load_script("maintainer_checks_skipall", "maintainer_checks.py")
    code = mod.main(
        [
            "--skip-version",
            "--skip-changelog",
            "--skip-docs-index",
            "--skip-example-catalog",
            "--skip-public-api",
        ]
    )
    assert code == 2


def test_maintainer_checks_load_script_missing_file() -> None:
    mod = _load_script("maintainer_checks_noscript", "maintainer_checks.py")
    with pytest.raises(FileNotFoundError, match="maintainer helper script not found"):
        mod._load_script("x", "definitely_missing_replayt_helper_404.py")


def test_maintainer_checks_real_repo_full() -> None:
    mod = _load_script("maintainer_checks_replayt", "maintainer_checks.py")
    root = Path(__file__).resolve().parents[1]
    report = mod.maintainer_checks_report(root, changelog_nonempty=True)

    assert report["ok"] is True, report


def test_example_catalog_contract_real_repo_snapshot_matches() -> None:
    mod = _load_script("example_catalog_contract_replayt", "example_catalog_contract.py")
    root = Path(__file__).resolve().parents[1]

    report = mod.check_snapshot(root / "docs" / "EXAMPLE_CATALOG_CONTRACT.json")

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
