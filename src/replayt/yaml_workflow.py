from __future__ import annotations

from pathlib import Path
from typing import Any

from replayt.types import RetryPolicy
from replayt.workflow import Workflow


def load_workflow_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover
        msg = "Install replayt with the `yaml` extra: pip install replayt[yaml]"
        raise RuntimeError(msg) from e
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a mapping")
    return raw


def workflow_from_spec(spec: dict[str, Any]) -> Workflow:
    """Build a runnable workflow from a small declarative YAML spec."""

    name = str(spec.get("name", "workflow"))
    version = str(spec.get("version", "1"))
    wf = Workflow(name, version=version)
    wf.set_initial(str(spec["initial"]))

    edges = spec.get("edges") or []
    if isinstance(edges, list):
        for e in edges:
            if isinstance(e, dict) and "from" in e and "to" in e:
                wf.note_transition(str(e["from"]), str(e["to"]))

    steps = spec.get("steps") or {}
    if not isinstance(steps, dict):
        raise ValueError("steps must be a mapping of state name -> step config")

    for state_name, raw_cfg in steps.items():
        cfg = raw_cfg or {}
        if not isinstance(cfg, dict):
            raise ValueError(f"step {state_name!r} must be a mapping")
        retry_cfg = cfg.get("retry") or {}
        retries = RetryPolicy(
            max_attempts=int(retry_cfg.get("max_attempts", 1)),
            backoff_seconds=float(retry_cfg.get("backoff_seconds", 0.0)),
        )

        def make_handler(step_name: str, step_cfg: dict[str, Any]):
            def handler(ctx):
                for key in step_cfg.get("require", []):
                    if ctx.get(str(key)) is None:
                        raise ValueError(f"Missing required context key: {key}")

                set_values = step_cfg.get("set") or {}
                if not isinstance(set_values, dict):
                    raise ValueError(f"step {step_name!r} field 'set' must be a mapping")
                for key, value in set_values.items():
                    ctx.set(str(key), value)

                approval = step_cfg.get("approval")
                if approval is not None:
                    if not isinstance(approval, dict) or "id" not in approval:
                        raise ValueError(f"step {step_name!r} approval must include an id")
                    approval_id = str(approval["id"])
                    if ctx.is_approved(approval_id):
                        return str(approval.get("on_approve", step_cfg.get("next", ""))) or None
                    if ctx.is_rejected(approval_id):
                        return str(approval.get("on_reject", "")) or None
                    ctx.request_approval(
                        approval_id,
                        summary=str(approval.get("summary", f"Approve step {step_name}?")),
                        details=approval.get("details") or {},
                    )

                branch = step_cfg.get("branch")
                if branch is not None:
                    if not isinstance(branch, dict) or "key" not in branch or "cases" not in branch:
                        raise ValueError(f"step {step_name!r} branch must include key and cases")
                    key = str(branch["key"])
                    value = ctx.get(key)
                    cases = branch["cases"]
                    if not isinstance(cases, dict):
                        raise ValueError(f"step {step_name!r} branch cases must be a mapping")
                    if value in cases:
                        return str(cases[value])
                    default_next = branch.get("default")
                    return str(default_next) if default_next not in (None, "") else None

                next_state = step_cfg.get("next")
                return str(next_state) if next_state not in (None, "") else None

            return handler

        wf.step(str(state_name), retries=retries)(make_handler(str(state_name), cfg))

    return wf
