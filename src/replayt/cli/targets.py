"""Resolve MODULE:VAR, .py, and .yaml workflow targets."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import typer

from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec


def _workflow_objects(obj: Any) -> list[tuple[str, Workflow]]:
    return [(name, value) for name, value in vars(obj).items() if isinstance(value, Workflow)]


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
    workflows = _workflow_objects(module)
    if len(workflows) == 1:
        return workflows[0][1]
    if workflows:
        names = ", ".join(name for name, _ in workflows)
        raise typer.BadParameter(
            f"Python workflow file {path} defines multiple Workflow objects ({names}); "
            "rename the one you want to `wf` or `workflow`."
        )
    raise typer.BadParameter(
        f"Python workflow file {path} must define `wf` or `workflow`, "
        "or exactly one top-level Workflow object."
    )


def _module_import_bad_parameter(target: str, mod_name: str, exc: ModuleNotFoundError) -> typer.BadParameter:
    """Turn import failures into onboarding-friendly CLI errors (common footguns)."""

    missing = getattr(exc, "name", None)
    if missing == mod_name:
        msg = (
            f"Could not import module {mod_name!r} from target {target!r}. "
            "Check spelling and your current working directory. "
            "If this is your own code, install it editable from the project root (`pip install -e .`) "
            "or put your package or `src/` tree on `PYTHONPATH` before running replayt. "
            "You can also pass a trusted `workflow.py` or `.yaml` path instead of MODULE:VAR. "
            "After the import works, `replayt doctor --target TARGET` checks the graph without executing."
        )
    else:
        inner = repr(missing) if missing else "a dependency"
        msg = (
            f"Importing {mod_name!r} for target {target!r} failed: {inner} is missing "
            "(not installed or not on PYTHONPATH). "
            "Install that dependency or fix imports inside your package, then retry."
        )
    return typer.BadParameter(msg)


def load_target(target: str) -> Workflow:
    """Resolve *target* to a :class:`~replayt.workflow.Workflow`.

    ``*.py`` paths are loaded with :func:`importlib.util.spec_from_file_location` and
    :meth:`importlib.abc.Loader.exec_module` (same trust model as ``python path/to/file.py``).
    Use only trusted files; prefer ``MODULE:VAR`` from installed
    packages or YAML workflows when inputs are less trusted.
    """
    path = Path(target)
    looks_like_file = path.suffix in {".py", ".yaml", ".yml"} and path.is_file()
    if looks_like_file:
        if path.suffix == ".py":
            obj = load_python_file(path)
        else:
            obj = workflow_from_spec(load_workflow_yaml(path))
    elif ":" in target:
        mod_name, attr = target.split(":", 1)
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:
            raise _module_import_bad_parameter(target, mod_name, exc) from exc
        if not hasattr(mod, attr):
            workflows = _workflow_objects(mod)
            if workflows:
                names = ", ".join(name for name, _ in workflows)
                raise typer.BadParameter(
                    f"Module {mod_name!r} has no attribute {attr!r}; available Workflow objects: {names}"
                )
            raise typer.BadParameter(
                f"Module {mod_name!r} has no attribute {attr!r} and exports no Workflow objects."
            )
        obj = getattr(mod, attr)
    else:
        if not path.exists():
            raise typer.BadParameter(
                f"Expected MODULE:VAR, workflow.py, or workflow.yaml target; path was not found: {path}"
            )
        raise typer.BadParameter("Target must be MODULE:VAR, .py, .yaml, or .yml")
    if not isinstance(obj, Workflow):
        raise typer.BadParameter(f"{target} did not resolve to a replayt.workflow.Workflow")
    return obj
