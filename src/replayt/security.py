from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from replayt.types import LogMode

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_SECRETISH_QUERY_PARTS = ("auth", "key", "password", "secret", "sig", "signature", "token")
_REDACTION_SENTINEL = {"_redacted": True}

# Common LLM-related env vars. replayt's OpenAI-compat client reads OPENAI_API_KEY / OPENAI_BASE_URL
# / REPLAYT_*; other names are audited for presence only (never values) for compliance reviews.
LLM_CREDENTIAL_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
)


def _env_nonempty(name: str) -> bool:
    raw = os.environ.get(name)
    return raw is not None and bool(str(raw).strip())


def llm_credential_env_presence() -> list[dict[str, bool]]:
    """Return fixed-name credential env flags for machine-readable doctor/config reports."""

    return [{"name": name, "present": _env_nonempty(name)} for name in LLM_CREDENTIAL_ENV_VARS]


def extraneous_llm_credential_env_names() -> tuple[str, ...]:
    """Env vars from :data:`LLM_CREDENTIAL_ENV_VARS` (except OPENAI_API_KEY) that are non-empty."""

    return tuple(n for n in LLM_CREDENTIAL_ENV_VARS if n != "OPENAI_API_KEY" and _env_nonempty(n))


def _base_url_safe_label(url: str) -> str:
    """Strip userinfo and query from a URL for operator-facing messages (avoid echoing secrets)."""

    parts = urlsplit(url)
    host = parts.hostname
    if host is not None:
        netloc = f"{host}:{parts.port}" if parts.port is not None else host
    else:
        netloc = ""
    return urlunsplit((parts.scheme, netloc, parts.path or "", "", ""))


@dataclass(frozen=True)
class TrustBoundaryCheck:
    name: str
    ok: bool
    detail: str
    hint: str | None = None
    soft: bool = True


def normalize_name_list(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or ():
        item = str(raw).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out)


def redact_named_fields(value: Any, *, field_names: list[str] | tuple[str, ...] | None) -> Any:
    names = {item.lower() for item in normalize_name_list(field_names)}
    if not names:
        return value
    return _redact_named_fields(value, names)


def _redact_named_fields(value: Any, field_names: set[str]) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            key_label = str(key).strip().lower()
            if key_label in field_names:
                out[key] = dict(_REDACTION_SENTINEL)
            else:
                out[key] = _redact_named_fields(item, field_names)
        return out
    if isinstance(value, list):
        return [_redact_named_fields(item, field_names) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_named_fields(item, field_names) for item in value)
    return value


def missing_actor_fields(
    actor: dict[str, Any] | None,
    *,
    required_fields: list[str] | tuple[str, ...] | None,
) -> list[str]:
    required = normalize_name_list(required_fields)
    if not required:
        return []
    actor_lookup = {str(key).strip().lower(): value for key, value in (actor or {}).items()}
    missing: list[str] = []
    for key in required:
        value = actor_lookup.get(key.lower(), None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def log_directory_permission_trust_checks(log_dir: Path | None) -> list[TrustBoundaryCheck]:
    """Soft warnings when the log directory mode is world-accessible (POSIX only; best-effort)."""

    if log_dir is None or os.name == "nt":
        return []
    try:
        resolved = log_dir.resolve()
        if not resolved.is_dir():
            return []
        mode = resolved.stat().st_mode
    except OSError:
        return []

    checks: list[TrustBoundaryCheck] = []
    if mode & stat.S_IROTH:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_dir_other_readable",
                ok=False,
                detail="log_dir is readable by users outside the owning user/group (world-readable bit)",
                hint="Use chmod to strip other read access, or place logs on a dedicated volume with stricter ACLs.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_dir_other_readable",
                ok=True,
                detail="log_dir is not world-readable",
            )
        )

    if mode & stat.S_IWOTH:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_dir_other_writable",
                ok=False,
                detail="log_dir is writable by users outside the owning user/group (world-writable bit)",
                hint="Strip other write on the log directory so unrelated accounts cannot append or tamper with JSONL.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_dir_other_writable",
                ok=True,
                detail="log_dir is not world-writable",
            )
        )
    return checks


def dotenv_trust_candidate_paths(
    *,
    cwd: Path | None = None,
    project_config_path: Path | str | None = None,
) -> list[Path]:
    """Paths to common `.env` files for permission audits (no reads of file contents)."""

    root = Path.cwd() if cwd is None else cwd
    seen: set[str] = set()
    out: list[Path] = []
    for candidate in (root / ".env",):
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    if project_config_path is not None:
        try:
            cfg_parent = Path(project_config_path).resolve().parent
        except OSError:
            cfg_parent = Path(project_config_path).parent
        env_next = cfg_parent / ".env"
        try:
            key = str(env_next.resolve())
        except OSError:
            key = str(env_next)
        if key not in seen:
            seen.add(key)
            out.append(env_next)
    return out


def dotenv_permission_trust_checks(candidate_paths: Sequence[Path]) -> list[TrustBoundaryCheck]:
    """Soft warnings when a discovered `.env` file is world-readable or world-writable (POSIX only)."""

    if os.name == "nt":
        return []
    existing: list[Path] = []
    resolved_seen: set[str] = set()
    for raw in candidate_paths:
        try:
            p = raw.resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = str(p)
        if key in resolved_seen:
            continue
        resolved_seen.add(key)
        existing.append(p)
    if not existing:
        return []

    bad_read: list[str] = []
    bad_write: list[str] = []
    for p in existing:
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        label = str(p)
        if mode & stat.S_IROTH:
            bad_read.append(label)
        if mode & stat.S_IWOTH:
            bad_write.append(label)

    checks: list[TrustBoundaryCheck] = []
    if bad_read:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_readable",
                ok=False,
                detail="world-readable .env file(s): " + ", ".join(bad_read),
                hint=(
                    "Use chmod 600 (or tighter) on .env files that hold API keys; "
                    "other OS accounts should not read them."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_readable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are world-readable",
            )
        )

    if bad_write:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_writable",
                ok=False,
                detail="world-writable .env file(s): " + ", ".join(bad_write),
                hint=(
                    "Strip world write on .env so unrelated accounts cannot replace your keys "
                    "with attacker-controlled values."
                ),
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_dotenv_other_writable",
                ok=True,
                detail=f"checked {len(existing)} .env file(s); none are world-writable",
            )
        )
    return checks


def trust_boundary_checks(*, base_url: str | None, log_mode: LogMode | str) -> list[TrustBoundaryCheck]:
    mode = log_mode.value if isinstance(log_mode, LogMode) else str(log_mode).strip().lower()
    checks: list[TrustBoundaryCheck] = []
    if mode == LogMode.full.value:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_mode",
                ok=False,
                detail="full log mode stores raw LLM request and response bodies on disk",
                hint="Prefer redacted or structured_only when prompts or outputs may contain PII or secrets.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_log_mode",
                ok=True,
                detail=f"{mode} avoids persisting raw LLM bodies",
            )
        )

    if not base_url:
        return checks

    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    is_local_http = parts.scheme == "http" and (host in _LOCAL_HOSTS or host.endswith(".localhost"))
    if parts.scheme == "https" or is_local_http:
        detail = "HTTPS" if parts.scheme == "https" else "HTTP is limited to a local host"
        checks.append(TrustBoundaryCheck(name="trust_base_url_transport", ok=True, detail=detail))
    else:
        safe = _base_url_safe_label(base_url)
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_transport",
                ok=False,
                detail=f"{safe} uses non-local plaintext HTTP or an unrecognized scheme",
                hint="Use HTTPS for remote providers; reserve plain HTTP for localhost gateways such as Ollama.",
            )
        )

    secretish_query_keys = sorted(
        {
            key
            for key, _value in parse_qsl(parts.query, keep_blank_values=True)
            if any(part in key.lower() for part in _SECRETISH_QUERY_PARTS)
        }
    )
    embedded_parts: list[str] = []
    if parts.username or parts.password:
        embedded_parts.append("user-info credentials")
    if secretish_query_keys:
        embedded_parts.append("query params " + ", ".join(secretish_query_keys))
    if embedded_parts:
        safe = _base_url_safe_label(base_url)
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_credentials",
                ok=False,
                detail=f"{safe} includes " + " and ".join(embedded_parts),
                hint="Move tokens into headers or env vars instead of embedding them in OPENAI_BASE_URL.",
            )
        )
    else:
        checks.append(
            TrustBoundaryCheck(
                name="trust_base_url_credentials",
                ok=True,
                detail="No embedded credentials detected in OPENAI_BASE_URL",
            )
        )
    return checks
