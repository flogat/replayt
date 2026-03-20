"""Resolve MODULE:VAR, .py, and .yaml workflow targets."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import typer

from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec


def load_python_file(path: Path) -> Any:
    module_name = f"replayt_user_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Could not import Python workflow file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("wf", "workflow"):
        if hasattr(module, attr):
            return getattr(module, attr)
    raise typer.BadParameter(f"Python workflow file {path} must define `wf` or `workflow`")


def load_target(target: str) -> Workflow:
    path = Path(target)
    looks_like_file = path.suffix in {".py", ".yaml", ".yml"} and path.is_file()
    if looks_like_file:
        if path.suffix == ".py":
            obj = load_python_file(path)
        else:
            obj = workflow_from_spec(load_workflow_yaml(path))
    elif ":" in target:
        mod_name, attr = target.split(":", 1)
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, attr)
    else:
        if not path.exists():
            raise typer.BadParameter(
                "Expected MODULE:VAR, workflow.py, or workflow.yaml target; path was not found"
            )
        raise typer.BadParameter("Target must be MODULE:VAR, .py, .yaml, or .yml")
    if not isinstance(obj, Workflow):
        raise typer.BadParameter(f"{target} did not resolve to a replayt.workflow.Workflow")
    return obj
