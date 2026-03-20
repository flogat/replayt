"""Typer CLI entrypoint for replayt."""

from __future__ import annotations

import typer

from replayt.cli import display as _display
from replayt.cli.commands import register_all

# Re-export for tests (REPLAY_HTML brace-escaping checks).
REPLAY_HTML_CSS = _display.REPLAY_HTML_CSS
_replay_html = _display.replay_html

app = typer.Typer(no_args_is_help=True, add_completion=False)
register_all(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
