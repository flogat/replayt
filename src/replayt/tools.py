from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T")

_log = logging.getLogger("replayt.tools")


class ToolRegistry:
    """Registers typed callables and records tool_call / tool_result events."""

    def __init__(
        self,
        emit: Callable[[str, dict[str, Any]], None],
        state_getter: Callable[[], str | None],
    ) -> None:
        self._emit = emit
        self._state_getter = state_getter
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, fn: Callable[..., T]) -> Callable[..., T]:
        self._tools[fn.__name__] = fn
        return fn

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        fn = self._tools[name]
        state = self._state_getter()
        self._emit("tool_call", {"state": state, "name": name, "arguments": arguments})
        try:
            sig = inspect.signature(fn)
            mod = inspect.getmodule(fn)
            globalns = vars(mod) if mod is not None else {}
            try:
                hints = get_type_hints(fn, globalns=globalns)
            except NameError:
                try:
                    hints = get_type_hints(fn)
                except NameError:
                    _log.warning(
                        "Could not resolve type hints for tool %r; validating arguments as Any",
                        name,
                    )
                    hints = {p: Any for p in sig.parameters}
            unknown = set(arguments) - set(sig.parameters)
            if unknown:
                raise TypeError(f"Unexpected tool arguments: {sorted(unknown)}")

            bound: dict[str, Any] = {}
            for param_name, param in sig.parameters.items():
                if param.kind not in {
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                }:
                    raise TypeError(f"Unsupported tool parameter kind for {param_name}: {param.kind}")
                if param_name not in arguments:
                    if param.default is inspect.Parameter.empty:
                        raise TypeError(f"Missing tool argument: {param_name}")
                    continue
                raw = arguments[param_name]
                ann = hints.get(param_name, Any)
                if ann is Any:
                    bound[param_name] = raw
                elif isinstance(ann, type) and issubclass(ann, BaseModel):
                    bound[param_name] = ann.model_validate(raw)
                else:
                    bound[param_name] = TypeAdapter(ann).validate_python(raw)
            result = fn(**bound)
            out: Any = result
            if isinstance(result, BaseModel):
                out = result.model_dump()
            self._emit("tool_result", {"state": state, "name": name, "ok": True, "result": out, "error": None})
            return result
        except Exception as e:  # noqa: BLE001
            self._emit(
                "tool_result",
                {
                    "state": state,
                    "name": name,
                    "ok": False,
                    "result": None,
                    "error": {"type": e.__class__.__name__, "message": str(e)},
                },
            )
            raise
