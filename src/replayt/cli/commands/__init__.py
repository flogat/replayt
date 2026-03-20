"""Register Typer subcommands grouped by area (run, inspect, export, doctor)."""

from __future__ import annotations

import typer


def register_all(app: typer.Typer) -> None:
    from replayt.cli.commands import doctor, export, inspect, run

    run.register(app)
    inspect.register(app)
    export.register(app)
    doctor.register(app)
