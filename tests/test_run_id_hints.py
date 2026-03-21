from __future__ import annotations

from pathlib import Path

from replayt.cli.config import DEFAULT_LOG_DIR
from replayt.cli.run_id_hints import suggested_runs_list_command


def test_suggested_runs_list_command_default_log_dir_only() -> None:
    assert (
        suggested_runs_list_command(cli_log_dir=DEFAULT_LOG_DIR, log_subdir=None, sqlite=None)
        == "replayt runs --limit 10"
    )


def test_suggested_runs_list_command_includes_log_dir_sqlite_subdir(tmp_path: Path) -> None:
    custom = tmp_path / "logs"
    db = tmp_path / "events.sqlite3"
    s = suggested_runs_list_command(
        cli_log_dir=custom,
        log_subdir="tenant_a",
        sqlite=db,
    )
    assert s == f"replayt runs --limit 10 --log-dir {custom} --log-subdir tenant_a --sqlite {db}"
