"""Tests for ``replayt.cli.distribution_metadata``."""

from __future__ import annotations

import json

import pytest


def test_build_distribution_metadata_report_when_metadata_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib.metadata import PackageNotFoundError

    def _raise(_name: str):
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.metadata", _raise)
    from replayt.cli.distribution_metadata import build_distribution_metadata_report

    r = build_distribution_metadata_report()
    assert r["schema"] == "replayt.distribution_metadata.v1"
    assert r["ok"] is False
    assert r["version"] is None
    assert r["requires_python"] is None
    assert r["summary"] is None
    assert r["license"] is None
    assert r["project_urls"] is None
    assert isinstance(r["detail"], str) and r["detail"]


def test_build_distribution_metadata_report_includes_summary_license_project_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeMeta:
        def __init__(self) -> None:
            self._fields = {
                "Version": "9.9.9",
                "Requires-Python": ">=3.10",
                "Summary": "Short summary line",
                "License": "Apache-2.0",
            }
            self._project_urls = [
                "Repository, https://example.org/repo",
                "Homepage, https://example.org/",
            ]

        def get(self, key: str, default=None):
            return self._fields.get(key, default)

        def get_all(self, key: str, failobj=None):
            if key == "Project-URL":
                return list(self._project_urls)
            return [] if failobj is None else failobj

    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _FakeMeta())
    from replayt.cli.distribution_metadata import build_distribution_metadata_report

    r = build_distribution_metadata_report()
    assert r["ok"] is True
    assert r["version"] == "9.9.9"
    assert r["requires_python"] == ">=3.10"
    assert r["summary"] == "Short summary line"
    assert r["license"] == "Apache-2.0"
    assert r["project_urls"] == [
        {"label": "Homepage", "url": "https://example.org/"},
        {"label": "Repository", "url": "https://example.org/repo"},
    ]


def test_build_distribution_metadata_report_matches_version_json() -> None:
    from replayt.cli.commands.version_cmd import build_version_report

    data = build_version_report()
    dm = data["distribution_metadata"]
    assert isinstance(dm, dict)
    assert dm["schema"] == "replayt.distribution_metadata.v1"
    if dm["ok"]:
        assert isinstance(dm["version"], str) and dm["version"].strip()
        assert dm["requires_python"] is not None
        blob = json.dumps(dm)
        assert ">=3.10" in blob or "3.10" in blob


def test_sorted_project_urls_ignores_non_sequence_get_all(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeMeta:
        def get(self, key: str, default=None):
            return {"Version": "1.0.0", "Requires-Python": ">=3.10"}.get(key, default)

        def get_all(self, key: str, failobj=None):
            if key == "Project-URL":
                return "not-a-list"  # type: ignore[return-value]
            return [] if failobj is None else failobj

    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _FakeMeta())
    from replayt.cli.distribution_metadata import build_distribution_metadata_report

    r = build_distribution_metadata_report()
    assert r["ok"] is True
    assert r["project_urls"] == []


def test_metadata_str_fields_ignore_non_string(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeMeta:
        def get(self, key: str, default=None):
            return {
                "Version": 2,
                "Requires-Python": ["3.10"],
                "Summary": None,
                "License": True,
            }.get(key, default)

        def get_all(self, key: str, failobj=None):
            return [] if failobj is None else failobj

    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _FakeMeta())
    from replayt.cli.distribution_metadata import build_distribution_metadata_report

    r = build_distribution_metadata_report()
    assert r["ok"] is True
    assert r["version"] is None
    assert r["requires_python"] is None
    assert r["summary"] is None
    assert r["license"] is None
