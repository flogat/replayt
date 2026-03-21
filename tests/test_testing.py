from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from replayt.persistence import JSONLStore
from replayt.testing import DryRunLLMClient, MockLLMClient, assert_events, run_with_mock
from replayt.types import LogMode
from replayt.workflow import Workflow


class Pick(BaseModel):
    label: str


def test_run_with_mock_llm_parse(tmp_path: Path) -> None:
    wf = Workflow("mocked", version="1")
    wf.set_initial("c")
    wf.note_transition("c", "done")

    @wf.step("c")
    def classify(ctx) -> str:
        out = ctx.llm.parse(Pick, messages=[{"role": "user", "content": "pick one"}])
        ctx.set("pick", out.model_dump())
        return "done"

    @wf.step("done")
    def done(ctx) -> None:
        return None

    mock = MockLLMClient()
    mock.enqueue('{"label": "a"}')
    store = JSONLStore(tmp_path)
    r = run_with_mock(wf, store, mock, log_mode=LogMode.redacted)
    assert r.status == "completed"
    events = assert_events(store, r.run_id, "structured_output", min_count=1)
    assert events[0].get("payload", {}).get("data") == {"label": "a"}


def test_dry_run_client_returns_valid_structure() -> None:
    client = DryRunLLMClient()
    result = client.chat_completions(messages=[{"role": "user", "content": "hello"}])
    assert "choices" in result
    assert len(result["choices"]) == 1
    assert "message" in result["choices"][0]
    assert "content" in result["choices"][0]["message"]
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["prompt_tokens"] == 0
    assert result["usage"]["completion_tokens"] == 0
    assert result["usage"]["total_tokens"] == 0


def test_dry_run_client_with_response_format() -> None:
    client = DryRunLLMClient()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "TestSchema",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                    "active": {"type": "boolean"},
                },
                "required": ["name", "count", "active"],
            },
        },
    }
    result = client.chat_completions(
        messages=[{"role": "user", "content": "test"}],
        response_format=response_format,
    )
    import json

    content = json.loads(result["choices"][0]["message"]["content"])
    assert content["name"] == ""
    assert content["count"] == 0
    assert content["active"] is False


def test_dry_run_client_in_workflow(tmp_path: Path) -> None:
    wf = Workflow("dry_wf", version="1")
    wf.set_initial("ask")

    @wf.step("ask")
    def ask(ctx) -> None:
        text = ctx.llm.complete_text(messages=[{"role": "user", "content": "hi"}])
        ctx.set("reply", text)
        return None

    client = DryRunLLMClient()
    store = JSONLStore(tmp_path)
    from replayt.runner import Runner

    runner = Runner(wf, store, llm_client=client)
    r = runner.run(inputs={})
    assert r.status == "completed"


def test_dry_run_client_infers_schema_from_parse_prompt() -> None:
    client = DryRunLLMClient()
    result = client.chat_completions(
        messages=[
            {
                "role": "system",
                "content": (
                    "You must respond with a single JSON object that validates against this JSON Schema "
                    '(return JSON only, no markdown):\n'
                    '{"type":"object","properties":{"label":{"type":"string"}},"required":["label"]}'
                ),
            },
            {"role": "user", "content": "pick one"},
        ]
    )
    import json

    content = json.loads(result["choices"][0]["message"]["content"])
    assert content == {"label": ""}


def test_dry_run_client_handles_nested_ref_schema() -> None:
    client = DryRunLLMClient()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "NestedSchema",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"$ref": "#/$defs/Address"},
                },
                "required": ["name", "address"],
                "$defs": {
                    "Address": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "zip": {"type": "integer"},
                        },
                        "required": ["city", "zip"],
                    }
                },
            },
        },
    }
    result = client.chat_completions(
        messages=[{"role": "user", "content": "test"}],
        response_format=response_format,
    )
    import json

    content = json.loads(result["choices"][0]["message"]["content"])
    assert content["name"] == ""
    assert content["address"]["city"] == ""
    assert content["address"]["zip"] == 0


def test_dry_run_client_respects_common_schema_constraints() -> None:
    class ConstrainedPayload(BaseModel):
        name: str = Field(min_length=2)
        count: int = Field(ge=1)
        ratio: float = Field(gt=0)
        tags: list[str] = Field(min_length=2)

    client = DryRunLLMClient()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "ConstrainedPayload",
            "schema": ConstrainedPayload.model_json_schema(),
        },
    }
    result = client.chat_completions(
        messages=[{"role": "user", "content": "test"}],
        response_format=response_format,
    )

    content = result["choices"][0]["message"]["content"]
    parsed = ConstrainedPayload.model_validate_json(content)
    assert len(parsed.name) >= 2
    assert parsed.count >= 1
    assert parsed.ratio > 0
    assert len(parsed.tags) >= 2
