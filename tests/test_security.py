from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from replayt.cli.config import inputs_file_trust_audit_paths
from replayt.cli.run_support import policy_hook_trust_audit_paths_for_cfg
from replayt.cli.targets import workflow_trust_audit_paths
from replayt.security import (
    EGRESS_TRUST_ENV_VARS,
    LLM_CREDENTIAL_ENV_VARS,
    approval_reason_missing,
    dotenv_permission_trust_checks,
    dotenv_trust_candidate_paths,
    egress_trust_env_presence,
    extraneous_llm_credential_env_names,
    inputs_file_permission_trust_checks,
    llm_credential_env_presence,
    log_directory_permission_trust_checks,
    missing_actor_fields,
    normalize_name_list,
    policy_hook_script_permission_trust_checks,
    redact_named_fields,
    sanitize_base_url_for_output,
    trust_boundary_checks,
    workflow_entrypoint_permission_trust_checks,
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
    log_dir.chmod(0o700)
    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_group_readable"].ok is True
    assert names["trust_log_dir_group_writable"].ok is True
    assert names["trust_log_dir_other_readable"].ok is True
    assert names["trust_log_dir_other_writable"].ok is True


def test_log_directory_permission_trust_checks_warns_group_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.chmod(0o770)
    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_group_readable"].ok is False
    assert names["trust_log_dir_group_writable"].ok is False


def test_log_directory_permission_trust_checks_warns_world_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.chmod(0o777)
    names = {c.name: c for c in log_directory_permission_trust_checks(log_dir)}
    assert names["trust_log_dir_group_readable"].ok is False
    assert names["trust_log_dir_group_writable"].ok is False
    assert names["trust_log_dir_other_readable"].ok is False
    assert names["trust_log_dir_other_writable"].ok is False


def test_log_directory_permission_trust_checks_stat_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    resolved_log_dir = str(log_dir.resolve())
    real_stat = Path.stat

    def boom(self: Path) -> os.stat_result:
        if str(self) == str(log_dir) or str(self) == resolved_log_dir:
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
    assert names["trust_log_dir_group_readable"].ok is False
    assert names["trust_log_dir_group_writable"].ok is False
    assert names["trust_log_dir_other_readable"].ok is False
    assert names["trust_log_dir_other_writable"].ok is False


def test_dotenv_permission_trust_checks_empty_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(os, "name", "nt")
    assert dotenv_permission_trust_checks([env_file]) == []


def test_dotenv_permission_trust_checks_empty_when_no_file(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    missing = tmp_path / ".env"
    assert dotenv_permission_trust_checks([missing]) == []


def test_dotenv_permission_trust_checks_ok_for_restrictive_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    env_file = tmp_path / ".env"
    env_file.write_text("K=v\n", encoding="utf-8")
    env_file.chmod(0o600)
    names = {c.name: c for c in dotenv_permission_trust_checks([env_file])}
    assert names["trust_dotenv_group_readable"].ok is True
    assert names["trust_dotenv_group_writable"].ok is True
    assert names["trust_dotenv_other_readable"].ok is True
    assert names["trust_dotenv_other_writable"].ok is True


def test_dotenv_permission_trust_checks_warns_group_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    env_file = tmp_path / ".env"
    env_file.write_text("K=v\n", encoding="utf-8")
    env_file.chmod(0o660)
    names = {c.name: c for c in dotenv_permission_trust_checks([env_file])}
    assert names["trust_dotenv_group_readable"].ok is False
    assert names["trust_dotenv_group_writable"].ok is False
    assert str(env_file) in names["trust_dotenv_group_readable"].detail


def test_dotenv_permission_trust_checks_warns_world_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    env_file = tmp_path / ".env"
    env_file.write_text("K=v\n", encoding="utf-8")
    env_file.chmod(0o666)
    names = {c.name: c for c in dotenv_permission_trust_checks([env_file])}
    assert names["trust_dotenv_group_readable"].ok is False
    assert names["trust_dotenv_group_writable"].ok is False
    assert names["trust_dotenv_other_readable"].ok is False
    assert names["trust_dotenv_other_writable"].ok is False
    assert str(env_file) in names["trust_dotenv_other_readable"].detail


def test_dotenv_permission_trust_checks_warns_via_mocked_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "name", "posix")
    env_file = tmp_path / ".env"
    env_file.write_text("K=v\n", encoding="utf-8")

    class _Stat:
        st_mode = stat.S_IFREG | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(Path, "stat", lambda self: _Stat())

    names = {c.name: c for c in dotenv_permission_trust_checks([env_file])}
    assert names["trust_dotenv_group_readable"].ok is False
    assert names["trust_dotenv_group_writable"].ok is False
    assert names["trust_dotenv_other_readable"].ok is False
    assert names["trust_dotenv_other_writable"].ok is False


def test_dotenv_trust_candidate_paths_dedupes_config_dir_with_cwd(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    cfg = pkg / "pyproject.toml"
    cfg.write_text("[project]\nname='x'\n", encoding="utf-8")
    paths = dotenv_trust_candidate_paths(cwd=pkg, project_config_path=cfg)
    assert len(paths) == 1
    assert paths[0] == pkg / ".env"


def test_dotenv_trust_candidate_paths_includes_distinct_cwd_and_config_parent(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg = b / "pyproject.toml"
    cfg.write_text("[project]\nname='x'\n", encoding="utf-8")
    paths = dotenv_trust_candidate_paths(cwd=a, project_config_path=cfg)
    assert paths == [a / ".env", b / ".env"]


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


def test_sanitize_base_url_for_output_strips_userinfo_and_query() -> None:
    safe = sanitize_base_url_for_output("https://user:secret@example.com/v1?token=secret&x=1")
    assert safe == "https://example.com/v1"


def test_normalize_name_list_dedupes_case_insensitive() -> None:
    assert normalize_name_list(["A", "a", " b ", ""]) == ("A", "b")


def test_redact_named_fields_nested() -> None:
    payload = {"outer": {"Token": "x", "keep": 1}}
    out = redact_named_fields(payload, field_names=["token"])
    assert out["outer"]["Token"] == {"_redacted": True}
    assert out["outer"]["keep"] == 1


def test_missing_actor_fields_reports_empty_strings() -> None:
    assert missing_actor_fields({"email": " "}, required_fields=["email"]) == ["email"]


def test_approval_reason_missing_rejects_blank_required_reason() -> None:
    assert approval_reason_missing(None, required=True) is True
    assert approval_reason_missing("   ", required=True) is True
    assert approval_reason_missing("approved under CAB-7", required=True) is False
    assert approval_reason_missing(None, required=False) is False


def test_llm_credential_env_presence_never_includes_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret")
    rows = llm_credential_env_presence()
    assert all(set(r.keys()) == {"name", "present"} for r in rows)
    anthropic = next(r for r in rows if r["name"] == "ANTHROPIC_API_KEY")
    assert anthropic["present"] is True
    blob = str(rows)
    assert "super-secret" not in blob


def test_extraneous_llm_credential_env_names_ignores_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert extraneous_llm_credential_env_names() == ()


def test_extraneous_llm_credential_env_names_lists_non_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert extraneous_llm_credential_env_names() == ("GROQ_API_KEY",)


def test_llm_credential_env_vars_sorted_and_covers_common_gateways() -> None:
    assert LLM_CREDENTIAL_ENV_VARS == tuple(sorted(LLM_CREDENTIAL_ENV_VARS))
    for name in (
        "DEEPSEEK_API_KEY",
        "FIREWORKS_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
        "PERPLEXITY_API_KEY",
        "TOGETHER_API_KEY",
        "XAI_API_KEY",
    ):
        assert name in LLM_CREDENTIAL_ENV_VARS


def test_egress_trust_env_vars_sorted() -> None:
    assert EGRESS_TRUST_ENV_VARS == tuple(sorted(EGRESS_TRUST_ENV_VARS))


def test_egress_trust_env_presence_never_includes_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@proxy.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/fake.pem")
    rows = egress_trust_env_presence()
    assert all(set(r.keys()) == {"name", "present"} for r in rows)
    http = next(r for r in rows if r["name"] == "HTTP_PROXY")
    assert http["present"] is True
    blob = str(rows)
    assert "secret" not in blob
    assert "proxy.invalid" not in blob


def test_egress_trust_env_presence_detects_lowercase_proxy_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX lowercase proxy alias check")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    rows = egress_trust_env_presence()
    https = next(r for r in rows if r["name"] == "HTTPS_PROXY")
    assert https["present"] is True


def test_workflow_entrypoint_permission_trust_checks_empty_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wf = tmp_path / "w.py"
    wf.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(os, "name", "nt")
    assert workflow_entrypoint_permission_trust_checks([wf]) == []


def test_workflow_entrypoint_permission_trust_checks_ok_for_restrictive_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    wf = tmp_path / "w.py"
    wf.write_text("x = 1\n", encoding="utf-8")
    wf.chmod(0o600)
    names = {c.name: c for c in workflow_entrypoint_permission_trust_checks([wf])}
    assert names["trust_workflow_entry_group_readable"].ok is True
    assert names["trust_workflow_entry_group_writable"].ok is True
    assert names["trust_workflow_entry_other_readable"].ok is True
    assert names["trust_workflow_entry_other_writable"].ok is True


def test_workflow_entrypoint_permission_trust_checks_warns_group_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    wf = tmp_path / "w.py"
    wf.write_text("x = 1\n", encoding="utf-8")
    wf.chmod(0o660)
    names = {c.name: c for c in workflow_entrypoint_permission_trust_checks([wf])}
    assert names["trust_workflow_entry_group_readable"].ok is False
    assert names["trust_workflow_entry_group_writable"].ok is False
    assert str(wf) in names["trust_workflow_entry_group_readable"].detail


def test_workflow_entrypoint_permission_trust_checks_warns_via_mocked_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "name", "posix")
    wf = tmp_path / "w.py"
    wf.write_text("x = 1\n", encoding="utf-8")

    class _Stat:
        st_mode = stat.S_IFREG | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(Path, "stat", lambda self: _Stat())

    names = {c.name: c for c in workflow_entrypoint_permission_trust_checks([wf])}
    assert names["trust_workflow_entry_group_readable"].ok is False
    assert names["trust_workflow_entry_group_writable"].ok is False
    assert names["trust_workflow_entry_other_readable"].ok is False
    assert names["trust_workflow_entry_other_writable"].ok is False


def test_workflow_trust_audit_paths_resolves_py_file(tmp_path: Path) -> None:
    wf = tmp_path / "w.py"
    wf.write_text("x = 1\n", encoding="utf-8")
    paths = workflow_trust_audit_paths(str(wf))
    assert paths == [wf.resolve()]


def test_workflow_trust_audit_paths_resolves_module_file() -> None:
    paths = workflow_trust_audit_paths("replayt.workflow:Workflow")
    assert len(paths) == 1
    assert paths[0].name == "workflow.py"
    assert paths[0].is_file()


def test_inputs_file_permission_trust_checks_empty_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inp = tmp_path / "in.json"
    inp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os, "name", "nt")
    assert inputs_file_permission_trust_checks([inp]) == []


def test_inputs_file_permission_trust_checks_ok_for_restrictive_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    inp = tmp_path / "in.json"
    inp.write_text("{}", encoding="utf-8")
    inp.chmod(0o600)
    names = {c.name: c for c in inputs_file_permission_trust_checks([inp])}
    assert names["trust_inputs_file_group_readable"].ok is True
    assert names["trust_inputs_file_group_writable"].ok is True
    assert names["trust_inputs_file_other_readable"].ok is True
    assert names["trust_inputs_file_other_writable"].ok is True


def test_inputs_file_permission_trust_checks_warns_group_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    inp = tmp_path / "in.json"
    inp.write_text("{}", encoding="utf-8")
    inp.chmod(0o660)
    names = {c.name: c for c in inputs_file_permission_trust_checks([inp])}
    assert names["trust_inputs_file_group_readable"].ok is False
    assert names["trust_inputs_file_group_writable"].ok is False
    assert str(inp) in names["trust_inputs_file_group_readable"].detail


def test_inputs_file_trust_audit_paths_skips_stdin_and_dedupes(tmp_path: Path) -> None:
    inp = tmp_path / "in.json"
    inp.write_text("{}", encoding="utf-8")
    assert inputs_file_trust_audit_paths(default_inputs_file="-") == []
    assert inputs_file_trust_audit_paths(default_inputs_file=None, explicit_inputs_file=Path("-")) == []
    resolved = inp.resolve()
    assert inputs_file_trust_audit_paths(
        default_inputs_file=str(resolved),
        explicit_inputs_file=inp,
    ) == [resolved]


def test_inputs_file_permission_trust_checks_warns_via_mocked_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "name", "posix")
    inp = tmp_path / "in.json"
    inp.write_text("{}", encoding="utf-8")

    class _Stat:
        st_mode = stat.S_IFREG | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(Path, "stat", lambda self: _Stat())

    names = {c.name: c for c in inputs_file_permission_trust_checks([inp])}
    assert names["trust_inputs_file_group_readable"].ok is False
    assert names["trust_inputs_file_group_writable"].ok is False
    assert names["trust_inputs_file_other_readable"].ok is False
    assert names["trust_inputs_file_other_writable"].ok is False


def test_policy_hook_script_permission_trust_checks_empty_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(os, "name", "nt")
    assert policy_hook_script_permission_trust_checks([script]) == []


def test_policy_hook_script_permission_trust_checks_ok_for_restrictive_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o600)
    names = {c.name: c for c in policy_hook_script_permission_trust_checks([script])}
    assert names["trust_policy_hook_script_group_readable"].ok is True
    assert names["trust_policy_hook_script_group_writable"].ok is True
    assert names["trust_policy_hook_script_other_readable"].ok is True
    assert names["trust_policy_hook_script_other_writable"].ok is True


def test_policy_hook_script_permission_trust_checks_warns_group_accessible(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits only")
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o660)
    names = {c.name: c for c in policy_hook_script_permission_trust_checks([script])}
    assert names["trust_policy_hook_script_group_readable"].ok is False
    assert names["trust_policy_hook_script_group_writable"].ok is False
    assert str(script) in names["trust_policy_hook_script_group_readable"].detail


def test_policy_hook_script_permission_trust_checks_warns_via_mocked_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "name", "posix")
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    class _Stat:
        st_mode = stat.S_IFREG | stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    monkeypatch.setattr(Path, "stat", lambda self: _Stat())

    names = {c.name: c for c in policy_hook_script_permission_trust_checks([script])}
    assert names["trust_policy_hook_script_group_readable"].ok is False
    assert names["trust_policy_hook_script_group_writable"].ok is False
    assert names["trust_policy_hook_script_other_readable"].ok is False
    assert names["trust_policy_hook_script_other_writable"].ok is False


def test_policy_hook_trust_audit_paths_for_cfg_resolves_direct_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for name in (
        "REPLAYT_RUN_HOOK",
        "REPLAYT_RESUME_HOOK",
        "REPLAYT_EXPORT_HOOK",
        "REPLAYT_SEAL_HOOK",
        "REPLAYT_VERIFY_SEAL_HOOK",
    ):
        monkeypatch.delenv(name, raising=False)
    paths = policy_hook_trust_audit_paths_for_cfg({"run_hook": script.name})
    assert paths == [script.resolve()]


def test_policy_hook_trust_audit_paths_for_cfg_python_argv1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hook.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for name in (
        "REPLAYT_RUN_HOOK",
        "REPLAYT_RESUME_HOOK",
        "REPLAYT_EXPORT_HOOK",
        "REPLAYT_SEAL_HOOK",
        "REPLAYT_VERIFY_SEAL_HOOK",
    ):
        monkeypatch.delenv(name, raising=False)
    paths = policy_hook_trust_audit_paths_for_cfg(
        {"run_hook": [sys.executable, str(script.name)]},
    )
    assert paths == [script.resolve()]


def test_policy_hook_trust_audit_paths_for_cfg_dedupes_across_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for name in (
        "REPLAYT_RUN_HOOK",
        "REPLAYT_RESUME_HOOK",
        "REPLAYT_EXPORT_HOOK",
        "REPLAYT_SEAL_HOOK",
        "REPLAYT_VERIFY_SEAL_HOOK",
    ):
        monkeypatch.delenv(name, raising=False)
    paths = policy_hook_trust_audit_paths_for_cfg(
        {"run_hook": script.name, "resume_hook": script.name},
    )
    assert paths == [script.resolve()]


def test_privacy_contract_hook_env_sorts_redact_key_names() -> None:
    from replayt.cli.run_support import _privacy_contract_hook_env

    env = _privacy_contract_hook_env(
        log_mode="structured_only",
        forbid_log_mode_full=False,
        redact_keys=("b", "A"),
    )
    assert env["REPLAYT_LOG_MODE"] == "structured_only"
    assert env["REPLAYT_FORBID_LOG_MODE_FULL"] == "0"
    assert env["REPLAYT_REDACT_KEYS_JSON"] == '["A", "b"]'
