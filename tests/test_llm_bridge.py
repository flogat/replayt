from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel

from replayt.llm import LLMBridge, LLMSettings, OpenAICompatClient
from replayt.types import LogMode


class Answer(BaseModel):
    value: int


def test_llm_bridge_with_settings_merges_experiment_into_effective() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="test-key", model="base-model")
    client = OpenAICompatClient(settings)
    bridge = (
        LLMBridge(emit=emit, client=client, log_mode=LogMode.redacted, state_getter=lambda: "s")
        .with_settings(experiment={"run_id": "r1"})
        .with_settings(experiment={"prompt_hash": "abc"})
    )

    canned = {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned):
        bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["experiment"] == {"run_id": "r1", "prompt_hash": "abc"}


def test_llm_bridge_with_settings_merges_into_effective_and_request() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="test-key", model="base-model")
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "step_a",
    ).with_settings(model="override-model", temperature=0.25, max_tokens=120)

    canned = {"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        out = bridge.complete_text(messages=[{"role": "user", "content": "hi"}])

    assert out == "hello"
    mock_cc.assert_called_once()
    call_kw = mock_cc.call_args.kwargs
    assert call_kw["model"] == "override-model"
    assert call_kw["temperature"] == 0.25
    assert call_kw["max_tokens"] == 120

    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["model"] == "override-model"
    assert req["effective"]["temperature"] == 0.25
    assert req["effective"]["max_tokens"] == 120

    resp = next(p for t, p in events if t == "llm_response")
    assert resp["effective"]["model"] == "override-model"
    assert "content_preview" in resp


def test_llm_bridge_structured_only_skips_content_preview() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.structured_only,
        state_getter=lambda: "s",
    )
    canned = {"choices": [{"message": {"content": "secret body"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned):
        bridge.complete_text(messages=[{"role": "user", "content": "x"}])

    req = next(p for t, p in events if t == "llm_request")
    assert "messages" not in req
    assert "messages_summary" not in req
    assert "effective" in req

    resp = next(p for t, p in events if t == "llm_response")
    assert "content_preview" not in resp
    assert "content" not in resp
    assert "latency_ms" in resp


def test_llm_bridge_parse_extracts_first_valid_json_object() -> None:
    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )
    canned = {
        "choices": [
            {
                "message": {
                    "content": 'Intro text\n```json\n{"value": 7}\n```\ntrailing noise {not json}',
                }
            }
        ],
        "usage": {},
    }

    with patch.object(client, "chat_completions", return_value=canned):
        out = bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])

    assert out.value == 7


def test_llm_bridge_parse_raises_for_missing_json_object() -> None:
    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )

    with patch.object(client, "chat_completions", return_value={"choices": [{"message": {"content": "no json"}}]}):
        with pytest.raises(ValueError):
            bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])


def test_extract_json_object_empty_string() -> None:
    from replayt.llm import _extract_json_object

    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json_object("")


def test_extract_json_object_whitespace_only() -> None:
    from replayt.llm import _extract_json_object

    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json_object("   \n\t  ")


def test_extract_json_object_nested() -> None:
    from replayt.llm import _extract_json_object

    text = 'before {"outer": {"inner": 1}} after'
    result = _extract_json_object(text)
    import json

    assert json.loads(result) == {"outer": {"inner": 1}}


def test_extract_json_object_ignores_arrays() -> None:
    from replayt.llm import _extract_json_object

    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json_object("[1, 2, 3]")


def test_openai_compat_invalid_json_body_raises() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html>not json</html>"
    mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "<html>", 0)
    mock_resp.raise_for_status = MagicMock()

    client = OpenAICompatClient(LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"))
    with patch.object(httpx.Client, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="not valid JSON"):
            client.chat_completions(messages=[{"role": "user", "content": "x"}])


def test_openai_compat_omits_authorization_without_api_key() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
    mock_resp.raise_for_status = MagicMock()

    client = OpenAICompatClient(LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"))
    with patch.object(httpx.Client, "post", return_value=mock_resp) as post:
        client.chat_completions(messages=[{"role": "user", "content": "x"}])
    hdrs = post.call_args.kwargs["headers"]
    assert "Authorization" not in hdrs
