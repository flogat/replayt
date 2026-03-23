from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from replayt.persistence import JSONLStore
from replayt.runner import Runner
from replayt.tools import ToolRegistry
from replayt.types import LogMode
from replayt.workflow import Workflow


class AddPayload(BaseModel):
    a: int
    b: int


class AddOut(BaseModel):
    total: int


def test_tool_registry(tmp_path: Path) -> None:
    wf = Workflow("tools")
    wf.set_initial("main")

    def add(payload: AddPayload) -> AddOut:
        return AddOut(total=payload.a + payload.b)

    @wf.step("main")
    def main(ctx) -> str | None:
        ctx.tools.register(add)
        r = ctx.tools.call("add", {"payload": {"a": 2, "b": 3}})
        ctx.set("sum", r.total)
        return None

    store = JSONLStore(tmp_path)
    r = Runner(wf, store, log_mode=LogMode.redacted)
    res = r.run()
    assert res.status == "completed"
    ev = store.load_events(res.run_id)
    assert any(e["type"] == "tool_result" and e["payload"].get("ok") for e in ev)


def test_tool_registry_rejects_unexpected_arguments_and_validates_primitives(tmp_path: Path) -> None:
    wf = Workflow("strict_tools")
    wf.set_initial("main")

    def repeat(message: str, count: int) -> str:
        return message * count

    @wf.step("main")
    def main(ctx) -> str | None:
        ctx.tools.register(repeat)
        with pytest.raises(TypeError):
            ctx.tools.call("repeat", {"message": "a", "count": 2, "extra": True})
        with pytest.raises(Exception):
            ctx.tools.call("repeat", {"message": "a", "count": "bad"})
        return None

    store = JSONLStore(tmp_path)
    result = Runner(wf, store, log_mode=LogMode.redacted).run()
    assert result.status == "completed"
    failed_results = [
        e
        for e in store.load_events(result.run_id)
        if e["type"] == "tool_result" and not e["payload"]["ok"]
    ]
    assert len(failed_results) == 2
    assert failed_results[0]["payload"]["error"]["type"] == "TypeError"


def test_tool_registry_openai_chat_tools_shape_and_sorted_names() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def z_last(x: int, y: int = 1) -> int:
        """Z tool.

        Second paragraph ignored.
        """
        return x + y

    def a_first(msg: str) -> str:
        """A tool."""
        return msg

    reg.register(z_last)
    reg.register(a_first)
    tools = reg.openai_chat_tools()
    assert [t["function"]["name"] for t in tools] == ["a_first", "z_last"]
    assert tools[0] == {
        "type": "function",
        "function": {
            "name": "a_first",
            "description": "A tool.",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        },
    }
    z = tools[1]["function"]
    assert z["name"] == "z_last"
    assert "description" in z
    assert z["parameters"]["required"] == ["x"]
    assert "y" not in (z["parameters"].get("required") or [])


def test_tool_registry_openai_chat_tools_pydantic_param() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def use_payload(payload: AddPayload) -> int:
        return payload.a + payload.b

    reg.register(use_payload)
    (tool,) = reg.openai_chat_tools()
    assert tool["function"]["name"] == "use_payload"
    props = tool["function"]["parameters"]["properties"]
    assert "payload" in props
    assert tool["function"]["parameters"]["required"] == ["payload"]


def test_tool_registry_openai_chat_tools_rejects_invalid_openai_function_name() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def ok_for_call(x: int) -> int:
        return x

    ok_for_call.__name__ = "bad.name"
    reg.register(ok_for_call)
    with pytest.raises(ValueError, match="not valid for OpenAI"):
        reg.openai_chat_tools()


def test_tool_registry_openai_chat_tools_rejects_var_positional() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def bad(*parts: str) -> str:
        return "".join(parts)

    reg.register(bad)
    with pytest.raises(TypeError, match="not supported for"):
        reg.openai_chat_tools()
