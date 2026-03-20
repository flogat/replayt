"""Project config discovery ([tool.replayt], .replaytrc.toml) and log path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from replayt.types import LogMode

SUPPORTED_CONFIG_KEYS = frozenset(
    {
        "log_dir",
        "log_mode",
        "sqlite",
        "provider",
        "model",
        "timeout",
        "strict_mirror",
        "resume_hook",
        "resume_hook_timeout",
    }
)

_PROJECT_CONFIG: dict[str, Any] | None = None
_PROJECT_CONFIG_PATH: str | None = None

DEFAULT_LOG_DIR = Path(".replayt/runs")


def load_project_config() -> tuple[dict[str, Any], str | None]:
    """Walk up from cwd looking for ``pyproject.toml`` (``[tool.replayt]``) or ``.replaytrc.toml``."""

    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return {}, None

    cur = Path.cwd().resolve()
    for directory in (cur, *cur.parents):
        rc = directory / ".replaytrc.toml"
        if rc.is_file():
            with open(rc, "rb") as f:
                data = tomllib.load(f)
            return {k: v for k, v in data.items() if k in SUPPORTED_CONFIG_KEYS}, str(rc)

        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            section = (data.get("tool") or {}).get("replayt")
            if isinstance(section, dict):
                return {k: v for k, v in section.items() if k in SUPPORTED_CONFIG_KEYS}, str(pyproject)
    return {}, None


def get_project_config() -> tuple[dict[str, Any], str | None]:
    global _PROJECT_CONFIG, _PROJECT_CONFIG_PATH  # noqa: PLW0603
    if _PROJECT_CONFIG is None:
        _PROJECT_CONFIG, _PROJECT_CONFIG_PATH = load_project_config()
    return _PROJECT_CONFIG, _PROJECT_CONFIG_PATH


def sanitize_log_subdir(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise typer.BadParameter("log_subdir must be non-empty")
    if os.path.sep in s or (os.altsep and os.altsep in s):
        raise typer.BadParameter("log_subdir must be a single path segment (no slashes)")
    if s.startswith(".") or s in (".", ".."):
        raise typer.BadParameter("log_subdir cannot start with '.'")
    return s


def resolve_log_dir(cli_log_dir: Path, log_subdir: str | None = None) -> Path:
    """Apply ``[tool.replayt]`` / ``REPLAYT_LOG_DIR`` defaults and optional tenant subdir."""

    cfg, _ = get_project_config()
    base = cli_log_dir
    if cli_log_dir == DEFAULT_LOG_DIR:
        if cfg.get("log_dir"):
            base = Path(str(cfg["log_dir"]))
        else:
            env_ld = os.environ.get("REPLAYT_LOG_DIR")
            if env_ld:
                base = Path(env_ld)
    if log_subdir is not None:
        base = base / sanitize_log_subdir(log_subdir)
    return base


def resolve_strict_mirror(cfg: dict[str, Any], *, sqlite: Path | None) -> bool:
    """Mirror write policy: explicit ``strict_mirror`` in config, else strict when ``--sqlite`` is used."""

    if "strict_mirror" in cfg:
        return bool(cfg["strict_mirror"])
    return sqlite is not None


def resume_hook_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    """Wall-clock limit for the ``resume_hook`` subprocess (seconds).

    ``None`` means no limit. Env ``REPLAYT_RESUME_HOOK_TIMEOUT`` overrides config; value ``<= 0``
    means unlimited. Default when unset: 120 seconds.
    """

    env_raw = os.environ.get("REPLAYT_RESUME_HOOK_TIMEOUT", "").strip()
    if env_raw:
        v = float(env_raw)
        return None if v <= 0 else v
    cfg_val = cfg.get("resume_hook_timeout")
    if cfg_val is not None:
        v = float(cfg_val)
        return None if v <= 0 else v
    return 120.0


def parse_log_mode(log_mode: str) -> LogMode:
    key = log_mode.strip().lower()
    if key == "redacted":
        return LogMode.redacted
    if key == "full":
        return LogMode.full
    if key in {"structured_only", "structured-only"}:
        return LogMode.structured_only
    raise typer.BadParameter("log_mode must be redacted, full, or structured_only")
