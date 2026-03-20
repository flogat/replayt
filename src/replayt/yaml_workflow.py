from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import create_model

from replayt.types import RetryPolicy
from replayt.workflow import Workflow

_TYPE_MAP: dict[str, type] = {"string": str, "integer": int, "float": float, "boolean": bool}


def _build_pydantic_model(name: str, schema: dict[str, Any]) -> type:
    fields: dict[str, Any] = {}
    for field_name, field_spec in schema.items():
        base_type = _TYPE_MAP.get(field_spec.get("type", "string"), str)
        if "enum" in field_spec:
            base_type = Literal[tuple(field_spec["enum"])]  # type: ignore[valid-type]
        fields[field_name] = (base_type, ...)
    return create_model(name, **fields)


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
            llm_spec = step_cfg.get("llm")
            if llm_spec is not None:
                if not isinstance(llm_spec, dict) or "prompt" not in llm_spec:
                    raise ValueError(f"step {step_name!r} llm must be a mapping with at least 'prompt'")
                if not llm_spec.get("output_key"):
                    raise ValueError(f"step {step_name!r} llm must include 'output_key'")

            def handler(ctx):
                for key in step_cfg.get("require", []):
                    if ctx.get(str(key)) is None:
                        raise ValueError(f"Missing required context key: {key}")

                set_values = step_cfg.get("set") or {}
                if not isinstance(set_values, dict):
                    raise ValueError(f"step {step_name!r} field 'set' must be a mapping")
                for key, value in set_values.items():
                    ctx.set(str(key), value)

                llm_cfg = step_cfg.get("llm")
                if llm_cfg is not None:
                    output_key = str(llm_cfg["output_key"])
                    raw_prompt: str = llm_cfg["prompt"]
                    prompt = raw_prompt.format_map({k: ctx.get(k, "") for k in ctx.data})

                    messages: list[dict[str, Any]] = []
                    if llm_cfg.get("system"):
                        messages.append({"role": "system", "content": str(llm_cfg["system"])})
                    messages.append({"role": "user", "content": prompt})

                    model_override = llm_cfg.get("model")
                    temperature = float(llm_cfg.get("temperature", 0.0))
                    llm_kwargs: dict[str, Any] = {"messages": messages, "temperature": temperature}
                    if model_override:
                        llm_kwargs["model"] = str(model_override)

                    schema = llm_cfg.get("schema")
                    if schema:
                        dynamic_model = _build_pydantic_model(f"{step_name}_output", schema)
                        result = ctx.llm.parse(dynamic_model, **llm_kwargs)
                        ctx.set(output_key, result.model_dump())
                    else:
                        text = ctx.llm.complete_text(**llm_kwargs)
                        ctx.set(output_key, text)

                approval = step_cfg.get("approval")
                if approval is not None:
                    if not isinstance(approval, dict) or "id" not in approval:
                        raise ValueError(f"step {step_name!r} approval must include an id")
                    approval_id = str(approval["id"])
                    on_approve = approval.get("on_approve", step_cfg.get("next", ""))
                    on_reject = approval.get("on_reject", "")
                    resolved_on_approve = str(on_approve) if on_approve not in (None, "") else None
                    resolved_on_reject = str(on_reject) if on_reject not in (None, "") else None
                    if ctx.is_approved(approval_id):
                        return resolved_on_approve
                    if ctx.is_rejected(approval_id):
                        return resolved_on_reject
                    ctx.request_approval(
                        approval_id,
                        summary=str(approval.get("summary", f"Approve step {step_name}?")),
                        details=approval.get("details") or {},
                        on_approve=resolved_on_approve,
                        on_reject=resolved_on_reject,
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
