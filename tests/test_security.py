from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from replayt.security import (
    log_directory_permission_trust_checks,
    missing_actor_fields,
    normalize_name_list,
    redact_named_fields,
    trust_boundary_checks,
)
from replayt.types import LogMode


def test_log_dir_permission_trust_checks_empty_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(os, "name", "nt")
    assert log_directory_permission_trust_checks(log_dir) == []


def test_log_directory_permission_trust_checks_ok_for_restrictive_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.chmod(0o770)
    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_other_readable"].ok is True
    assert names["trust_log_dir_other_writable"].ok is True


def test_log_directory_permission_trust_checks_warns_world_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.chmod(0o777)
    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_other_readable"].ok is False
    assert names["trust_log_dir_other_writable"].ok is False


def test_log_directory_permission_trust_checks_stat_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    real_stat = Path.stat

    def boom(self: Path) -> os.stat_result:
        if self.resolve() == log_dir.resolve():
            raise OSError("boom")
        return real_stat(self)

    monkeypatch.setattr(Path, "stat", boom)
    assert log_directory_permission_trust_checks(log_dir) == []


def test_log_directory_permission_trust_checks_resolve_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_dir = MagicMock(spec=Path)
    log_dir.resolve.side_effect = OSError("nope")
    assert log_directory_permission_trust_checks(log_dir) == []


def test_log_directory_permission_trust_checks_warns_via_mocked_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise world-accessible warnings without relying on chmod semantics (e.g. umask)."""

    monkeypatch.setattr(os, "name", "posix")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    class _Stat:
        st_mode = stat.S_IFDIR | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(Path, "stat", lambda self: _Stat())

    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_other_readable"].ok is False
    assert names["trust_log_dir_other_writable"].ok is False


def test_trust_boundary_checks_messages_never_echo_url_password() -> None:
    secret = "not-for-stdout"
    url = f"https://user:{secret}@api.example.com/v1"
    checks = trust_boundary_checks(base_url=url, log_mode=LogMode.redacted)
    for check in checks:
        assert secret not in check.detail


def test_trust_boundary_checks_transport_warning_sanitizes_url() -> None:
    secret = "hunter2"
    url = f"http://x:{secret}@203.0.113.1/v1"
    checks = trust_boundary_checks(base_url=url, log_mode="redacted")
    transport = next(c for c in checks if c.name == "trust_base_url_transport")
    assert transport.ok is False
    assert secret not in transport.detail
    assert "203.0.113.1" in transport.detail


def test_trust_boundary_checks_https_ok() -> None:
    checks = trust_boundary_checks(base_url="https://api.example.com/v1", log_mode="redacted")
    names = {c.name: c for c in checks}
    assert names["trust_base_url_transport"].ok is True
    assert names["trust_base_url_credentials"].ok is True


def test_trust_boundary_checks_http_ipv6_localhost_ok() -> None:
    checks = trust_boundary_checks(base_url="http://[::1]:11434/v1", log_mode="redacted")
    transport = next(c for c in checks if c.name == "trust_base_url_transport")
    assert transport.ok is True


def test_trust_boundary_checks_secretish_query_key_surfaces_key_not_value() -> None:
    checks = trust_boundary_checks(
        base_url="https://api.example.com/v1?api_key=supersecret&other=1",
        log_mode="redacted",
    )
    cred = next(c for c in checks if c.name == "trust_base_url_credentials")
    assert cred.ok is False
    assert "api_key" in cred.detail
    assert "supersecret" not in cred.detail


def test_normalize_name_list_dedupes_case_insensitive() -> None:
    assert normalize_name_list(["A", "a", " b ", ""]) == ("A", "b")


def test_redact_named_fields_nested() -> None:
    payload = {"outer": {"Token": "x", "keep": 1}}
    out = redact_named_fields(payload, field_names=["token"])
    assert out["outer"]["Token"] == {"_redacted": True}
    assert out["outer"]["keep"] == 1


def test_missing_actor_fields_reports_empty_strings() -> None:
    assert missing_actor_fields({"email": " "}, required_fields=["email"]) == ["email"]
