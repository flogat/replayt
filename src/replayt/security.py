from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from replayt.types import LogMode

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_SECRETISH_QUERY_PARTS = ("auth", "key", "password", "secret", "sig", "signature", "token")
_REDACTION_SENTINEL = {"_redacted": True}


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
    except OSError:
        return []
    if not resolved.is_dir():
        return []
    try:
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
