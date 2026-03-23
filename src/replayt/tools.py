from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T")

_log = logging.getLogger("replayt.tools")

# OpenAI Chat Completions ``tools[].function.name`` (and most gateways): ASCII identifier-like, max 64.
_OPENAI_TOOL_FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_UNSUPPORTED_PARAM_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }
)


def _first_paragraph_doc(fn: Callable[..., Any]) -> str | None:
    raw = inspect.getdoc(fn)
    if not raw:
        return None
    para = raw.strip().split("\n\n", 1)[0].strip()
    return para or None


def _openai_parameters_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema object for OpenAI ``function.parameters`` from type hints."""

    sig = inspect.signature(fn)
    mod = inspect.getmodule(fn)
    globalns = vars(mod) if mod is not None else {}
    try:
        hints = get_type_hints(fn, globalns=globalns)
    except NameError:
        try:
            hints = get_type_hints(fn)
        except NameError as exc:
            msg = f"Could not resolve type hints for OpenAI tool schema: {fn.__name__!r}"
            raise TypeError(msg) from exc

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param.kind in _UNSUPPORTED_PARAM_KINDS:
            msg = (
                f"Tool {fn.__name__!r}: parameter {param_name!r} is not supported for "
                "OpenAI tool schemas (use keyword-compatible parameters only)."
            )
            raise TypeError(msg)
        ann = hints.get(param_name, Any)
        properties[param_name] = TypeAdapter(ann).json_schema()
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = sorted(required)
    return out


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

    def openai_chat_tools(self) -> list[dict[str, Any]]:
        """OpenAI Chat Completions ``tools`` payloads for registered handlers (composition helper).

        Each entry matches ``{"type": "function", "function": {"name", "parameters", ...}}``.
        Parameter JSON Schemas come from Pydantic :class:`~pydantic.TypeAdapter` (same hints as
        :meth:`call`). Docstrings supply ``function.description`` (first paragraph only).

        This does **not** route model tool calls through :class:`~replayt.llm.LLMBridge`; call the
        vendor SDK inside one ``@wf.step``, pass this list as ``tools=``, then execute chosen calls
        through :meth:`call` so ``tool_call`` / ``tool_result`` lines stay in JSONL.
        """

        out: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            if not _OPENAI_TOOL_FUNCTION_NAME_RE.fullmatch(name):
                msg = (
                    f"Tool name {name!r} is not valid for OpenAI Chat Completions "
                    "(use 1-64 characters: ASCII letters, digits, underscore, or hyphen only)."
                )
                raise ValueError(msg)
            fn = self._tools[name]
            func: dict[str, Any] = {"name": name, "parameters": _openai_parameters_schema(fn)}
            desc = _first_paragraph_doc(fn)
            if desc:
                func["description"] = desc
            out.append({"type": "function", "function": func})
        return out

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
