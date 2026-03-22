"""Workflow graph validation and dry-check JSON helpers for the CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

import typer

from replayt.workflow import Workflow

VALIDATE_REPORT_SCHEMA = "replayt.validate_report.v1"

InputsFileOrigin = Literal["cli", "env", "project"]


def _inputs_file_missing_hint(origin: InputsFileOrigin | None) -> str:
    if origin == "project":
        return (
            "That path comes from [tool.replayt] inputs_file (resolved relative to your config file). "
            "Edit `.replaytrc.toml` or `pyproject.toml`, run `replayt config` to see the resolved default, "
            "or pass `--inputs-file PATH` for this run only. See docs/CONFIG.md."
        )
    if origin == "env":
        return (
            "That path comes from REPLAYT_INPUTS_FILE. Unset it, point it at a real JSON file, "
            "use `-` for stdin, or pass `--inputs-file` / `--inputs-json` to override for this command."
        )
    return (
        "Verify the path exists. Relative paths resolve from the current working directory "
        "(see `replayt config` for project defaults when you expected config to supply inputs)."
    )


def _read_json_text_file(path: Path, *, label: str, origin: InputsFileOrigin | None = None) -> str:
    if not path.is_file():
        hint = _inputs_file_missing_hint(origin)
        raise typer.BadParameter(f"{label} file not found: {path}. {hint}")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise typer.BadParameter(f"{label} file must be UTF-8 text ({e})") from e
    return raw.strip() or "{}"


def _read_json_from_stdin(*, label: str) -> str:
    try:
        raw = sys.stdin.read()
    except OSError as e:
        raise typer.BadParameter(f"{label}: could not read stdin ({e})") from e
    return raw.strip() or "{}"


def _is_stdin_inputs_path(path: Path) -> bool:
    return path == Path("-")


def _json_parse_hint(label: str) -> str:
    if label == "inputs":
        return (
            "; tip: use --inputs-file PATH, --inputs-file - (stdin), "
            "or --inputs-json @PATH / @- (stdin) to avoid shell quoting"
        )
    return ""


def inputs_json_from_options(
    inputs_json: str | None,
    inputs_file: Path | None,
    input_value: list[str] | None = None,
    *,
    inputs_file_origin: InputsFileOrigin | None = None,
) -> str | None:
    if inputs_json is not None and inputs_file is not None:
        raise typer.BadParameter("Use only one of --inputs-json or --inputs-file")
    base_raw: str | None = None
    if inputs_file is not None:
        if _is_stdin_inputs_path(inputs_file):
            base_raw = _read_json_from_stdin(label="--inputs-file")
        else:
            base_raw = _read_json_text_file(
                inputs_file, label="--inputs-file", origin=inputs_file_origin
            )
    elif inputs_json is not None and inputs_json.startswith("@"):
        file_ref = inputs_json[1:].strip()
        if not file_ref:
            raise typer.BadParameter("--inputs-json @path form requires a file path, e.g. --inputs-json @inputs.json")
        if file_ref == "-":
            base_raw = _read_json_from_stdin(label="--inputs-json @-")
        else:
            base_raw = _read_json_text_file(
                Path(file_ref), label="--inputs-json @path", origin=inputs_file_origin
            )
    else:
        base_raw = inputs_json
    if not input_value:
        return base_raw
    merged: dict[str, Any] = {}
    if base_raw is not None:
        merged = parse_json_object_option(base_raw, label="inputs")
    for raw_item in input_value:
        path, value = _parse_input_assignment(raw_item)
        _assign_input_value(merged, path, value)
    return json.dumps(merged)


def _parse_input_assignment(raw_item: str) -> tuple[list[str], Any]:
    if "=" not in raw_item:
        raise typer.BadParameter(f"--input must be key=value, got: {raw_item!r}")
    raw_key, raw_value = raw_item.split("=", 1)
    key = raw_key.strip()
    if not key:
        raise typer.BadParameter(f"--input must use a non-empty key before '=', got: {raw_item!r}")
    path = [part.strip() for part in key.split(".")]
    if any(not part for part in path):
        raise typer.BadParameter(
            f"--input dotted paths cannot contain empty segments, got: {raw_key!r}"
        )
    return path, _coerce_input_value(raw_value)


def _coerce_input_value(raw_value: str) -> Any:
    stripped = raw_value.strip()
    if not stripped:
        return raw_value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return raw_value


def _assign_input_value(target: dict[str, Any], path: list[str], value: Any) -> None:
    current: dict[str, Any] = target
    walked: list[str] = []
    for part in path[:-1]:
        walked.append(part)
        existing = current.get(part)
        if existing is None:
            child: dict[str, Any] = {}
            current[part] = child
            current = child
            continue
        if not isinstance(existing, dict):
            dotted = ".".join(walked)
            raise typer.BadParameter(
                f"--input path {'.'.join(path)!r} cannot descend into {dotted!r} because that value is not an object"
            )
        current = existing
    current[path[-1]] = value


def check_json_object_string(raw: str | None, *, label: str) -> tuple[bool, str | None]:
    if raw is None:
        return True, None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"{label}: {e}{_json_parse_hint(label)}"
    if not isinstance(obj, dict):
        return False, f"{label}: must be a JSON object"
    try:
        json.dumps(obj)
    except (TypeError, ValueError) as e:
        return False, f"{label}: must be JSON-serializable ({e})"
    return True, None


def parse_json_object_option(raw: str, *, label: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"{label} must be valid JSON ({e}){_json_parse_hint(label)}") from e
    if not isinstance(obj, dict):
        raise typer.BadParameter(f"{label} must be a JSON object")
    return obj


def validation_report(
    *,
    target: str,
    wf: Workflow,
    strict_graph: bool,
    errors: list[str],
    warnings: list[str],
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
        "warnings": list(warnings),
        "errors": list(errors) + extra_errors,
    }


def validate_workflow_graph(wf: Workflow, *, strict_graph: bool = False) -> tuple[list[str], list[str]]:
    """Graph / handler checks without executing steps (no LLM).

    Returns ``(errors, warnings)``. Warnings do not fail validation.
    """

    errors: list[str] = []
    warnings: list[str] = []
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
    elif len(wf.step_names()) >= 2 and not wf.edges():
        warnings.append(
            "Workflow has 2+ steps but no declared transitions (empty note_transition / YAML-inferred "
            "edges). Any step-to-step return value is allowed at runtime unless you use --strict-graph."
        )
    return errors, warnings
