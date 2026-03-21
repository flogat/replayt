from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from replayt.llm import LLMBridge, LLMSettings, OpenAICompatClient
from replayt.types import LogMode


class Answer(BaseModel):
    value: int


class _FakeStreamResp:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self):
        yield self._body


class _FakeHTTPClient:
    def __init__(self, responder) -> None:
        self._responder = responder
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._responder(*args, **kwargs)

    def close(self) -> None:
        return None


@contextmanager
def _stream_cm(resp: _FakeStreamResp):
    yield resp


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


def test_llm_bridge_float_max_tokens_from_defaults_passed_to_client() -> None:
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
    ).with_settings(max_tokens=4096.0)

    canned = {"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        out = bridge.complete_text(messages=[{"role": "user", "content": "hi"}])

    assert out == "hello"
    assert mock_cc.call_args.kwargs["max_tokens"] == 4096
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["max_tokens"] == 4096


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


def test_llm_bridge_with_settings_passes_stop_to_client_and_effective() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="k", model="m")
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "s",
    ).with_settings(stop=["###", "END"])

    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    assert mock_cc.call_args.kwargs["stop"] == ["###", "END"]
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["stop"] == ["###", "END"]


def test_llm_bridge_with_settings_passes_penalties_and_seed_to_client() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="k", model="m")
    client = OpenAICompatClient(settings)
    bridge = (
        LLMBridge(emit=emit, client=client, log_mode=LogMode.redacted, state_getter=lambda: "s")
        .with_settings(frequency_penalty=0.5, presence_penalty=-1.0, seed=99)
    )
    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    call_kw = mock_cc.call_args.kwargs
    assert call_kw["frequency_penalty"] == 0.5
    assert call_kw["presence_penalty"] == -1.0
    assert call_kw["seed"] == 99
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["frequency_penalty"] == 0.5
    assert req["effective"]["presence_penalty"] == -1.0
    assert req["effective"]["seed"] == 99


def test_llm_bridge_with_settings_supports_top_p_and_provider_routing() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="test-key", provider="openrouter", model="base-model")
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "route_model",
    ).with_settings(provider="openai", base_url="https://gateway.example/v1", top_p=0.2)

    canned = {"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        out = bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    assert out == "hello"
    call_kw = mock_cc.call_args.kwargs
    assert call_kw["model"] == "gpt-4o-mini"
    assert call_kw["base_url"] == "https://gateway.example/v1"
    assert call_kw["top_p"] == 0.2
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["provider"] == "openai"
    assert req["effective"]["base_url"] == "https://gateway.example/v1"
    assert req["effective"]["top_p"] == 0.2
    assert req["effective"]["model"] == "gpt-4o-mini"


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


def test_llm_bridge_parse_extracts_json_object_from_fenced_response() -> None:
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


def test_llm_bridge_parse_prefers_last_json_object() -> None:
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
                    "content": '{"value": 1} noise {"value": 42}',
                }
            }
        ],
        "usage": {},
    }

    with patch.object(client, "chat_completions", return_value=canned):
        out = bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])

    assert out.value == 42


def test_llm_bridge_parse_raises_for_missing_json_object() -> None:
    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )

    with patch.object(client, "chat_completions", return_value={"choices": [{"message": {"content": "no json"}}]}):
        with pytest.raises(ValueError, match="No JSON object found"):
            bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])


def test_llm_bridge_parse_rejects_oversized_response() -> None:
    settings = LLMSettings(api_key="k", model="m", max_parse_response_chars=100)
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )
    huge = "x" * 101
    with patch.object(bridge, "_request_text", return_value=(huge, {"model": "m"})):
        with pytest.raises(ValueError, match="exceeds max_parse_response_chars"):
            bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])


def test_llm_bridge_parse_rejects_oversized_json_schema() -> None:
    from pydantic import BaseModel, Field

    class Wide(BaseModel):
        a: str = Field(description="x" * 400)
        b: str = Field(description="y" * 400)

    settings = LLMSettings(api_key="k", model="m", max_schema_json_chars=120)
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )
    with pytest.raises(ValueError, match="max_schema_json_chars"):
        bridge.parse(Wide, messages=[{"role": "user", "content": "hi"}])


def test_llm_bridge_parse_with_native_response_format_logs_mode() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    ).with_settings(native_response_format=True)
    canned = {"choices": [{"message": {"content": '{"value": 7}'}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        out = bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])

    assert out.value == 7
    response_format = mock_cc.call_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Answer"
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["structured_output_mode"] == "native_json_schema"


def test_llm_bridge_parse_emits_structured_output_failed_on_validation_error() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )
    content = '{"value": "oops"}'

    with patch.object(client, "chat_completions", return_value={"choices": [{"message": {"content": content}}]}):
        with pytest.raises(Exception, match="value"):
            bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])

    failure = next(p for t, p in events if t == "structured_output_failed")
    assert failure["schema_name"] == "Answer"
    assert failure["stage"] == "schema_validate"
    assert failure["structured_output_mode"] == "prompt_only"
    assert failure["response_chars"] == len(content)


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


def test_extract_json_object_prefers_last_dict() -> None:
    from replayt.llm import _extract_json_object

    text = '{"a": 1} middle {"b": 2}'
    assert json.loads(_extract_json_object(text)) == {"b": 2}


def test_extract_json_object_ignores_arrays() -> None:
    from replayt.llm import _extract_json_object

    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json_object("[1, 2, 3]")


def test_extract_json_object_too_many_braces_aborts() -> None:
    from replayt.llm import _extract_json_object

    text = "{" * 60_000 + '{"z": 1}'
    with pytest.raises(ValueError, match="Too many"):
        _extract_json_object(text, max_brace_starts=50_000)


def test_openai_compat_invalid_json_body_raises() -> None:
    body = b"<html>not json</html>"
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"),
        http_client=_FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(body))),
    )
    with pytest.raises(RuntimeError, match="not valid JSON") as excinfo:
        client.chat_completions(messages=[{"role": "user", "content": "x"}])
    assert "body_bytes=" in str(excinfo.value)
    assert "not json" not in str(excinfo.value).lower()


def test_openai_compat_omits_authorization_without_api_key() -> None:
    body = b'{"choices":[{"message":{"content":"{}"}}]}'
    fake_http = _FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(body)))
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"),
        http_client=fake_http,
    )
    client.chat_completions(messages=[{"role": "user", "content": "x"}])
    hdrs = fake_http.calls[0][1]["headers"]
    assert "Authorization" not in hdrs


def test_openai_compat_supports_base_url_and_top_p_overrides() -> None:
    body = b'{"choices":[{"message":{"content":"{}"}}]}'
    fake_http = _FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(body)))
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"),
        http_client=fake_http,
    )
    client.chat_completions(
        messages=[{"role": "user", "content": "x"}],
        base_url="https://gateway.example/v1",
        top_p=0.3,
        frequency_penalty=0.1,
        presence_penalty=0.2,
        seed=3,
    )
    args, kwargs = fake_http.calls[0]
    assert args[1] == "https://gateway.example/v1/chat/completions"
    assert kwargs["json"]["top_p"] == 0.3
    assert kwargs["json"]["frequency_penalty"] == 0.1
    assert kwargs["json"]["presence_penalty"] == 0.2
    assert kwargs["json"]["seed"] == 3


def test_openai_compat_rejects_response_over_max_bytes() -> None:
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1", max_response_bytes=10),
        http_client=_FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(b"x" * 20))),
    )
    with pytest.raises(RuntimeError, match="max_response_bytes"):
        client.chat_completions(messages=[{"role": "user", "content": "x"}])


def test_openai_compat_rejects_content_length_over_max_bytes() -> None:
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1", max_response_bytes=10),
        http_client=_FakeHTTPClient(
            lambda *a, **k: _stream_cm(_FakeStreamResp(b"{}", headers={"content-length": "999"}))
        ),
    )
    with pytest.raises(RuntimeError, match="Content-Length"):
        client.chat_completions(messages=[{"role": "user", "content": "x"}])
