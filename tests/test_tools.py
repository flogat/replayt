from __future__ import annotations

import json
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


def test_apply_openai_chat_tool_calls_empty() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")
    assert reg.apply_openai_chat_tool_calls(None) == []
    assert reg.apply_openai_chat_tool_calls([]) == []


def test_apply_openai_chat_tool_calls_order_and_json_args() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(typ: str, payload: dict[str, Any]) -> None:
        events.append((typ, payload))

    reg = ToolRegistry(emit=emit, state_getter=lambda: "s1")

    @reg.register
    def first(x: int) -> str:
        return f"a{x}"

    @reg.register
    def second(y: str) -> str:
        return y.upper()

    tcs = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "first", "arguments": json.dumps({"x": 3})},
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "second", "arguments": {"y": "hi"}},
        },
    ]
    out = reg.apply_openai_chat_tool_calls(tcs)
    assert out == ["a3", "HI"]
    assert [e[0] for e in events] == ["tool_call", "tool_result", "tool_call", "tool_result"]
    assert events[0][1]["name"] == "first"
    assert events[2][1]["name"] == "second"


def test_apply_openai_chat_tool_calls_rejects_bad_shape() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    @reg.register
    def ok() -> int:
        return 1

    with pytest.raises(TypeError, match="expected dict"):
        reg.apply_openai_chat_tool_calls([object()])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="expected type 'function'"):
        reg.apply_openai_chat_tool_calls(
            [{"type": "other", "function": {"name": "ok", "arguments": "{}"}}]
        )

    with pytest.raises(ValueError, match="missing or invalid function.name"):
        reg.apply_openai_chat_tool_calls(
            [{"type": "function", "function": {"name": "", "arguments": "{}"}}]
        )

    with pytest.raises(ValueError, match=r"tool_calls\[0\].*invalid JSON"):
        reg.apply_openai_chat_tool_calls(
            [{"type": "function", "function": {"name": "ok", "arguments": "not-json"}}]
        )


def test_tool_registry_anthropic_messages_tools_shape_and_sorted_names() -> None:
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
    tools = reg.anthropic_messages_tools()
    assert [t["name"] for t in tools] == ["a_first", "z_last"]
    assert tools[0] == {
        "name": "a_first",
        "description": "A tool.",
        "input_schema": {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    }
    z = tools[1]
    assert z["name"] == "z_last"
    assert z["description"].startswith("Z tool.")
    assert z["input_schema"]["required"] == ["x"]
    assert "y" not in (z["input_schema"].get("required") or [])


def test_tool_registry_anthropic_messages_tools_rejects_invalid_name() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def ok_for_call(x: int) -> int:
        return x

    ok_for_call.__name__ = "bad.name"
    reg.register(ok_for_call)
    with pytest.raises(ValueError, match="not valid for Anthropic"):
        reg.anthropic_messages_tools()


def test_apply_anthropic_tool_use_blocks_empty_and_skips_text() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")
    assert reg.apply_anthropic_tool_use_blocks(None) == []
    assert reg.apply_anthropic_tool_use_blocks([]) == []
    assert reg.apply_anthropic_tool_use_blocks([{"type": "text", "text": "hi"}]) == []


def test_apply_anthropic_tool_use_blocks_order_and_inputs() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(typ: str, payload: dict[str, Any]) -> None:
        events.append((typ, payload))

    reg = ToolRegistry(emit=emit, state_getter=lambda: "s1")

    @reg.register
    def first(x: int) -> str:
        return f"a{x}"

    @reg.register
    def second(y: str) -> str:
        return y.upper()

    blocks = [
        {"type": "text", "text": "thinking"},
        {"type": "tool_use", "id": "tu_1", "name": "first", "input": {"x": 3}},
        {"type": "tool_use", "id": "tu_2", "name": "second", "input": json.dumps({"y": "hi"})},
    ]
    out = reg.apply_anthropic_tool_use_blocks(blocks)
    assert out == ["a3", "HI"]
    assert [e[0] for e in events] == ["tool_call", "tool_result", "tool_call", "tool_result"]
    assert events[0][1]["name"] == "first"
    assert events[2][1]["name"] == "second"


def test_apply_anthropic_tool_use_blocks_rejects_bad_shape() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    @reg.register
    def ok() -> int:
        return 1

    with pytest.raises(TypeError, match="expected dict"):
        reg.apply_anthropic_tool_use_blocks([object()])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="tool_use missing or invalid name"):
        reg.apply_anthropic_tool_use_blocks(
            [{"type": "tool_use", "id": "x", "name": "", "input": {}}]
        )

    with pytest.raises(ValueError, match=r"content\[0\].*invalid JSON"):
        reg.apply_anthropic_tool_use_blocks(
            [{"type": "tool_use", "id": "x", "name": "ok", "input": "not-json"}]
        )


def test_tool_registry_bedrock_converse_tools_shape_and_sorted_names() -> None:
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
    tools = reg.bedrock_converse_tools()
    assert [t["toolSpec"]["name"] for t in tools] == ["a_first", "z_last"]
    assert tools[0] == {
        "toolSpec": {
            "name": "a_first",
            "description": "A tool.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                }
            },
        }
    }
    z = tools[1]["toolSpec"]
    assert z["name"] == "z_last"
    assert z["description"].startswith("Z tool.")
    assert z["inputSchema"]["json"]["required"] == ["x"]
    assert "y" not in (z["inputSchema"]["json"].get("required") or [])


def test_tool_registry_bedrock_converse_tools_rejects_invalid_name() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    def ok_for_call(x: int) -> int:
        return x

    ok_for_call.__name__ = "bad.name"
    reg.register(ok_for_call)
    with pytest.raises(ValueError, match="not valid for Amazon Bedrock"):
        reg.bedrock_converse_tools()


def test_apply_bedrock_converse_tool_use_blocks_empty_and_skips_text() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")
    assert reg.apply_bedrock_converse_tool_use_blocks(None) == []
    assert reg.apply_bedrock_converse_tool_use_blocks([]) == []
    assert reg.apply_bedrock_converse_tool_use_blocks([{"text": "hi"}]) == []


def test_apply_bedrock_converse_tool_use_blocks_order_and_inputs() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(typ: str, payload: dict[str, Any]) -> None:
        events.append((typ, payload))

    reg = ToolRegistry(emit=emit, state_getter=lambda: "s1")

    @reg.register
    def first(x: int) -> str:
        return f"a{x}"

    @reg.register
    def second(y: str) -> str:
        return y.upper()

    blocks = [
        {"text": "thinking"},
        {
            "toolUse": {
                "toolUseId": "tu_1",
                "name": "first",
                "input": {"x": 3},
            }
        },
        {
            "toolUse": {
                "toolUseId": "tu_2",
                "name": "second",
                "input": json.dumps({"y": "hi"}),
            }
        },
    ]
    out = reg.apply_bedrock_converse_tool_use_blocks(blocks)
    assert out == ["a3", "HI"]
    assert [e[0] for e in events] == ["tool_call", "tool_result", "tool_call", "tool_result"]
    assert events[0][1]["name"] == "first"
    assert events[2][1]["name"] == "second"


def test_apply_bedrock_converse_tool_use_blocks_rejects_bad_shape() -> None:
    def emit(_typ: str, _payload: dict[str, Any]) -> None:
        return None

    reg = ToolRegistry(emit=emit, state_getter=lambda: "main")

    @reg.register
    def ok() -> int:
        return 1

    with pytest.raises(TypeError, match="expected dict"):
        reg.apply_bedrock_converse_tool_use_blocks([object()])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="toolUse missing or invalid name"):
        reg.apply_bedrock_converse_tool_use_blocks(
            [{"toolUse": {"toolUseId": "x", "name": "", "input": {}}}]
        )

    with pytest.raises(ValueError, match=r"content\[0\].*invalid JSON"):
        reg.apply_bedrock_converse_tool_use_blocks(
            [{"toolUse": {"toolUseId": "x", "name": "ok", "input": "not-json"}}]
        )

    with pytest.raises(TypeError, match="toolUse must be a dict"):
        reg.apply_bedrock_converse_tool_use_blocks([{"toolUse": "nope"}])
