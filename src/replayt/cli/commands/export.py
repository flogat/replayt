"""Commands: seal, report, report-diff, export-run, bundle-export."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.cli.config import DEFAULT_LOG_DIR, parse_log_mode, resolve_log_dir
from replayt.cli.display import replay_html
from replayt.cli.stores import read_store
from replayt.cli.targets import load_target
from replayt.export_run import events_to_jsonl_lines
from replayt.graph_export import workflow_to_mermaid
from replayt.persistence.jsonl import validate_run_id


def cmd_seal(
    run_id: str = typer.Argument(..., help="Run id (JSONL file basename without .jsonl)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Manifest output path (default: <log-dir>/<run_id>.seal.json).",
    ),
    output: Literal["text", "json"] = typer.Option("text", "--output", "-o", help="text or json."),
) -> None:
    """Write a SHA-256 manifest for a JSONL run log (best-effort audit helper; not cryptographic proof)."""

    log_dir = resolve_log_dir(log_dir, log_subdir)

    try:
        safe_run_id = validate_run_id(run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    log_root = log_dir.resolve()
    path = (log_dir / f"{safe_run_id}.jsonl").resolve()
    try:
        path.relative_to(log_root)
    except ValueError:
        typer.echo(
            f"Refusing to seal JSONL outside log directory: {path} is not under {log_root}",
            err=True,
        )
        raise typer.Exit(code=2)
    if not path.is_file():
        typer.echo(
            f"No JSONL at {path} (``seal`` applies to the primary JSONL file, not SQLite-only stores).",
            err=True,
        )
        raise typer.Exit(code=2)

    raw = path.read_bytes()
    file_digest = hashlib.sha256(raw).hexdigest()
    line_digests = [hashlib.sha256(line).hexdigest() for line in raw.splitlines(keepends=True)]
    manifest: dict[str, Any] = {
        "schema": "replayt.seal.v1",
        "run_id": safe_run_id,
        "jsonl_path": str(path.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(line_digests),
        "line_sha256": line_digests,
        "file_sha256": file_digest,
        "note": (
            "Best-effort integrity record. Anyone who can write the log directory can replace "
            "both the JSONL and this manifest; use WORM storage or external signing for stronger guarantees."
        ),
    }
    out_path = out if out is not None else log_dir / f"{safe_run_id}.seal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if output == "json":
        typer.echo(json.dumps({**manifest, "manifest_path": str(out_path.resolve())}, indent=2))
    else:
        typer.echo(f"wrote {out_path} ({len(line_digests)} lines, file_sha256={file_digest[:12]}...)")


def cmd_report(
    run_id: str = typer.Argument(..., help="Run ID to generate report for"),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Output file path (default: stdout)"),
    style: Literal["default", "stakeholder"] = typer.Option(
        "default",
        "--style",
        help="default (full) or stakeholder (approvals-first; omits tool/token sections).",
    ),
) -> None:
    """Generate a self-contained HTML report for a run."""

    from replayt.cli.report_template import build_run_report_html

    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    report = build_run_report_html(run_id, events, style=style)

    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        typer.echo(f"Wrote report to {out_path}")
    else:
        typer.echo(report)


def cmd_report_diff(
    run_a: str = typer.Argument(..., metavar="RUN_A"),
    run_b: str = typer.Argument(..., metavar="RUN_B"),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    out: str | None = typer.Option(None, "--out", help="Write HTML here (default: stdout)."),
) -> None:
    """HTML side-by-side comparison of two runs from local JSONL (no model calls)."""

    from replayt.cli.report_template import build_report_diff_html, collect_report_context

    log_dir = resolve_log_dir(log_dir, log_subdir)
    with read_store(log_dir, sqlite) as store:
        events_a = store.load_events(run_a)
        events_b = store.load_events(run_b)
    if not events_a:
        typer.echo(f"No events for run_id={run_a!r}", err=True)
        raise typer.Exit(code=2)
    if not events_b:
        typer.echo(f"No events for run_id={run_b!r}", err=True)
        raise typer.Exit(code=2)
    ctx_a = collect_report_context(events_a)
    ctx_b = collect_report_context(events_b)
    doc = build_report_diff_html(run_a, run_b, ctx_a, ctx_b)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(doc, encoding="utf-8")
        typer.echo(f"Wrote {out_path}")
    else:
        typer.echo(doc)


def cmd_export_run(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", help="Output path (.tar.gz)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    export_mode: str = typer.Option(
        "redacted",
        "--export-mode",
        case_sensitive=False,
        help="Sanitize copy: redacted | full | structured_only",
    ),
) -> None:
    """Write a shareable .tar.gz: sanitized events.jsonl + manifest.json."""

    log_dir = resolve_log_dir(log_dir, log_subdir)
    lm = parse_log_mode(export_mode)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    lines = events_to_jsonl_lines(events, lm)
    bundle = b"".join(lines)
    digest = hashlib.sha256(bundle).hexdigest()
    manifest: dict[str, Any] = {
        "schema": "replayt.export_bundle.v1",
        "run_id": run_id,
        "export_mode": export_mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "line_count": len(lines),
        "events_jsonl_sha256": digest,
        "note": "Sanitized copy for sharing; not necessarily byte-identical to on-disk JSONL.",
    }
    man_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tf:
        ti = tarfile.TarInfo(name=f"{run_id}/events.jsonl")
        ti.size = len(bundle)
        tf.addfile(ti, io.BytesIO(bundle))
        ti2 = tarfile.TarInfo(name=f"{run_id}/manifest.json")
        ti2.size = len(man_bytes)
        tf.addfile(ti2, io.BytesIO(man_bytes))
    typer.echo(f"wrote {out.resolve()} ({len(lines)} events, sha256={digest[:16]}...)")


def cmd_bundle_export(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out", help="Output path (.tar.gz)."),
    log_dir: Path = typer.Option(DEFAULT_LOG_DIR, "--log-dir"),
    log_subdir: str | None = typer.Option(None, "--log-subdir"),
    sqlite: Path | None = typer.Option(None, "--sqlite"),
    export_mode: str = typer.Option(
        "redacted",
        "--export-mode",
        case_sensitive=False,
        help="Sanitized events.jsonl: redacted | full | structured_only",
    ),
    report_style: Literal["default", "stakeholder"] = typer.Option(
        "stakeholder",
        "--report-style",
        help="Which replayt report variant to include.",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Optional MODULE:wf / workflow.py for workflow.mmd.txt (Mermaid); .py executes code—trusted only.",
    ),
) -> None:
    """Write a stakeholder-oriented .tar.gz: HTML report, replay timeline HTML, sanitized events.jsonl, manifest."""

    from replayt.cli.report_template import build_run_report_html

    log_dir = resolve_log_dir(log_dir, log_subdir)
    lm = parse_log_mode(export_mode)
    with read_store(log_dir, sqlite) as store:
        events = store.load_events(run_id)
    if not events:
        typer.echo(f"No events for run_id={run_id!r}", err=True)
        raise typer.Exit(code=2)

    report_html = build_run_report_html(run_id, events, style=report_style)
    timeline_html = replay_html(run_id, events)
    lines = events_to_jsonl_lines(events, lm)
    bundle = b"".join(lines)
    digest = hashlib.sha256(bundle).hexdigest()
    mermaid_txt: bytes | None = None
    if target is not None:
        wf = load_target(target)
        mermaid_txt = (workflow_to_mermaid(wf).rstrip() + "\n").encode("utf-8")

    manifest: dict[str, Any] = {
        "schema": "replayt.bundle_export.v1",
        "run_id": run_id,
        "export_mode": export_mode,
        "report_style": report_style,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": ["report.html", "timeline.html", "events.jsonl", "manifest.json"]
        + (["workflow.mmd.txt"] if mermaid_txt else []),
        "events_jsonl_sha256": digest,
        "note": "Stakeholder bundle: HTML views + sanitized JSONL; not necessarily byte-identical to on-disk JSONL.",
    }
    man_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    prefix = run_id
    with tarfile.open(out, "w:gz") as tf:
        for name, body in (
            ("report.html", report_html.encode("utf-8")),
            ("timeline.html", timeline_html.encode("utf-8")),
            ("events.jsonl", bundle),
            ("manifest.json", man_bytes),
        ):
            ti = tarfile.TarInfo(name=f"{prefix}/{name}")
            ti.size = len(body)
            tf.addfile(ti, io.BytesIO(body))
        if mermaid_txt is not None:
            ti = tarfile.TarInfo(name=f"{prefix}/workflow.mmd.txt")
            ti.size = len(mermaid_txt)
            tf.addfile(ti, io.BytesIO(mermaid_txt))
    typer.echo(f"wrote {out.resolve()} ({len(lines)} events, sha256={digest[:16]}...)")


def register(app: typer.Typer) -> None:
    app.command("seal")(cmd_seal)
    app.command("report")(cmd_report)
    app.command("report-diff")(cmd_report_diff)
    app.command("export-run")(cmd_export_run)
    app.command("bundle-export")(cmd_bundle_export)
