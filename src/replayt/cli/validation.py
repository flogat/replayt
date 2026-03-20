"""Workflow graph validation and dry-check JSON helpers for the CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from replayt.workflow import Workflow

VALIDATE_REPORT_SCHEMA = "replayt.validate_report.v1"


def inputs_json_from_options(
    inputs_json: str | None,
    inputs_file: Path | None,
) -> str | None:
    if inputs_json is not None and inputs_file is not None:
        raise typer.BadParameter("Use only one of --inputs-json or --inputs-file")
    if inputs_file is not None:
        if not inputs_file.is_file():
            raise typer.BadParameter(f"--inputs-file not found: {inputs_file}")
        try:
            raw = inputs_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise typer.BadParameter(f"--inputs-file must be UTF-8 text ({e})") from e
        return raw.strip() or "{}"
    return inputs_json


def check_json_object_string(raw: str | None, *, label: str) -> tuple[bool, str | None]:
    if raw is None:
        return True, None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"{label}: {e}"
    if not isinstance(obj, dict):
        return False, f"{label}: must be a JSON object"
    try:
        json.dumps(obj)
    except (TypeError, ValueError) as e:
        return False, f"{label}: must be JSON-serializable ({e})"
    return True, None


def validation_report(
    *,
    target: str,
    wf: Workflow,
    strict_graph: bool,
    errors: list[str],
    inputs_json: str | None,
    metadata_json: str | None,
    experiment_json: str | None,
) -> dict[str, Any]:
    inp_ok, inp_err = check_json_object_string(inputs_json, label="inputs")
    meta_ok, meta_err = check_json_object_string(metadata_json, label="metadata")
    exp_ok, exp_err = check_json_object_string(experiment_json, label="experiment")
    extra_errors: list[str] = []
    if inp_err:
        extra_errors.append(inp_err)
    if meta_err:
        extra_errors.append(meta_err)
    if exp_err:
        extra_errors.append(exp_err)
    return {
        "schema": VALIDATE_REPORT_SCHEMA,
        "ok": len(errors) == 0 and inp_ok and meta_ok and exp_ok,
        "target": target,
        "workflow": {
            "name": wf.name,
            "version": wf.version,
            "state_count": len(wf.step_names()),
            "edge_count": len(wf.edges()),
        },
        "strict_graph": strict_graph,
        "errors": list(errors) + extra_errors,
    }


def validate_workflow_graph(wf: Workflow, *, strict_graph: bool = False) -> list[str]:
    """Graph / handler checks without executing steps (no LLM)."""

    errors: list[str] = []
    if not wf.initial_state:
        errors.append("initial state is not set (call set_initial)")
    declared = set(wf.step_names())
    if wf.initial_state and wf.initial_state not in declared:
        errors.append(f"initial state {wf.initial_state!r} is not a declared @wf.step")
    edges = wf.edges()
    for src, dst in edges:
        if dst not in declared:
            errors.append(f"transition target {dst!r} (from {src!r}) is not a declared step")
        if src not in declared:
            errors.append(f"transition source {src!r} is not a declared step")

    if wf.initial_state and edges:
        reachable: set[str] = set()
        queue = [wf.initial_state]
        adj: dict[str, list[str]] = {}
        for src, dst in edges:
            adj.setdefault(src, []).append(dst)
        while queue:
            node = queue.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in reachable:
                    queue.append(neighbor)
        orphans = declared - reachable
        for orphan in sorted(orphans):
            errors.append(f"state {orphan!r} is unreachable from initial state {wf.initial_state!r}")

    for name in wf.step_names():
        try:
            wf.get_handler(name)
        except KeyError:
            errors.append(f"step {name!r} has no handler")
    if strict_graph and len(wf.step_names()) >= 2 and not wf.edges():
        errors.append(
            "strict graph: multi-state workflow has no declared transitions; use "
            "wf.note_transition(from_state, to_state), or YAML next/branch/approval (edges inferred)"
        )
    return errors
