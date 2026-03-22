from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import BaseModel, create_model

from replayt.llm import LLMBridge, LLMSettings, OpenAICompatClient
from replayt.types import LogMode


class Answer(BaseModel):
    value: int


def _sha256_json(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def test_llm_bridge_llm_response_logs_finish_reason_and_provider_ids() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="k", model="m")
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(emit=emit, client=client, log_mode=LogMode.redacted, state_getter=lambda: "s")

    canned = {
        "id": "chatcmpl-test-1",
        "system_fingerprint": "fp_ab12",
        "choices": [{"message": {"content": "hi"}, "finish_reason": "length"}],
        "usage": {"total_tokens": 2},
    }

    with patch.object(client, "chat_completions", return_value=canned):
        bridge.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)

    resp = next(p for t, p in events if t == "llm_response")
    assert resp["finish_reason"] == "length"
    assert resp["chat_completion_id"] == "chatcmpl-test-1"
    assert resp["system_fingerprint"] == "fp_ab12"


def test_llm_bridge_llm_response_omits_optional_ids_when_absent() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(emit=emit, client=client, log_mode=LogMode.redacted, state_getter=lambda: "s")
    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned):
        bridge.complete_text(messages=[{"role": "user", "content": "x"}], temperature=0.0)

    resp = next(p for t, p in events if t == "llm_response")
    assert resp["finish_reason"] is None
    assert "chat_completion_id" not in resp
    assert "system_fingerprint" not in resp


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


def test_llm_bridge_with_settings_passes_extra_body_to_client_and_effective() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="k", model="m", extra_body={"provider_hint": {"tier": "base"}})
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "s",
    ).with_settings(extra_body={"reasoning": {"effort": "high"}})

    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0)

    assert mock_cc.call_args.kwargs["extra_body"] == {
        "provider_hint": {"tier": "base"},
        "reasoning": {"effort": "high"},
    }
    req = next(p for t, p in events if t == "llm_request")
    assert req["effective"]["extra_body"] == {
        "provider_hint": {"tier": "base"},
        "reasoning": {"effort": "high"},
    }


def test_llm_bridge_complete_text_emits_stable_request_fingerprints() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    settings = LLMSettings(api_key="k", model="m")
    client = OpenAICompatClient(settings)
    bridge = LLMBridge(emit=emit, client=client, log_mode=LogMode.redacted, state_getter=lambda: "s")
    messages = [{"role": "user", "content": "hi"}]
    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned):
        bridge.complete_text(messages=messages, temperature=0.0)

    req = next(p for t, p in events if t == "llm_request")
    resp = next(p for t, p in events if t == "llm_response")
    assert req["messages_sha256"] == _sha256_json(messages)
    assert req["effective_sha256"] == _sha256_json(req["effective"])
    assert "schema_sha256" not in req
    assert resp["messages_sha256"] == req["messages_sha256"]
    assert resp["effective_sha256"] == req["effective_sha256"]
    assert "schema_sha256" not in resp


def test_llm_bridge_call_extra_body_empty_dict_clears_defaults() -> None:
    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=lambda *_args, **_kwargs: None,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "s",
    ).with_settings(extra_body={"reasoning": {"effort": "medium"}})

    canned = {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    with patch.object(client, "chat_completions", return_value=canned) as mock_cc:
        bridge.complete_text(messages=[{"role": "user", "content": "hi"}], temperature=0.0, extra_body={})

    assert mock_cc.call_args.kwargs["extra_body"] is None


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
    with patch.object(
        bridge,
        "_request_text",
        return_value=(huge, {"model": "m"}, {}, {"latency_ms": 1, "usage": None, "finish_reason": None}),
    ):
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


def test_llm_bridge_parse_success_emits_schema_and_request_fingerprints() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.full,
        state_getter=lambda: "parse",
    )
    canned = {
        "id": "chatcmpl-parse-1",
        "system_fingerprint": "fp_parse",
        "choices": [{"message": {"content": '{"value": 7}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    with patch.object(client, "chat_completions", return_value=canned):
        out = bridge.parse(Answer, messages=[{"role": "user", "content": "hi"}])

    assert out.value == 7
    req = next(p for t, p in events if t == "llm_request")
    resp = next(p for t, p in events if t == "llm_response")
    structured = next(p for t, p in events if t == "structured_output")
    assert req["messages_sha256"] == _sha256_json(req["messages"])
    assert req["effective_sha256"] == _sha256_json(req["effective"])
    assert req["schema_sha256"] == _sha256_json(Answer.model_json_schema())
    assert resp["messages_sha256"] == req["messages_sha256"]
    assert resp["effective_sha256"] == req["effective_sha256"]
    assert resp["schema_sha256"] == req["schema_sha256"]
    assert structured["messages_sha256"] == req["messages_sha256"]
    assert structured["effective_sha256"] == req["effective_sha256"]
    assert structured["schema_sha256"] == req["schema_sha256"]
    assert structured["usage"] == canned["usage"]
    assert structured["finish_reason"] == "stop"
    assert structured["latency_ms"] == resp["latency_ms"]
    assert structured["chat_completion_id"] == "chatcmpl-parse-1"
    assert structured["system_fingerprint"] == "fp_parse"


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
    req = next(p for t, p in events if t == "llm_request")
    assert failure["schema_name"] == "Answer"
    assert failure["stage"] == "schema_validate"
    assert failure["structured_output_mode"] == "prompt_only"
    assert failure["response_chars"] == len(content)
    assert failure["messages_sha256"] == req["messages_sha256"]
    assert failure["effective_sha256"] == req["effective_sha256"]
    assert failure["schema_sha256"] == req["schema_sha256"]
    assert failure["validation_issue_count"] == 1
    assert "validation_issues_truncated" not in failure
    issues = failure["validation_issues"]
    assert len(issues) == 1
    assert issues[0]["loc"] == ["value"]
    assert "validation" in issues[0]["msg"].lower() or "int" in issues[0]["msg"].lower()


def test_llm_bridge_parse_validation_issues_truncated_when_many_fields_fail() -> None:
    events: list[tuple[str, dict]] = []

    def emit(typ: str, payload: dict) -> None:
        events.append((typ, payload))

    Big = create_model("WideRow", **{f"f{i}": (int, ...) for i in range(40)})
    payload_obj = {f"f{i}": "nope" for i in range(40)}
    content = json.dumps(payload_obj)

    client = OpenAICompatClient(LLMSettings(api_key="k", model="m"))
    bridge = LLMBridge(
        emit=emit,
        client=client,
        log_mode=LogMode.redacted,
        state_getter=lambda: "parse",
    )

    with patch.object(client, "chat_completions", return_value={"choices": [{"message": {"content": content}}]}):
        with pytest.raises(Exception):
            bridge.parse(Big, messages=[{"role": "user", "content": "hi"}])

    failure = next(p for t, p in events if t == "structured_output_failed")
    assert failure["stage"] == "schema_validate"
    assert failure["validation_issue_count"] == 40
    assert len(failure["validation_issues"]) == 32
    assert failure["validation_issues_truncated"] is True


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


def test_openai_compat_401_without_api_key_hints_onboarding() -> None:
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1"),
        http_client=_FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(b"{}", status=401))),
    )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is unset") as excinfo:
        client.chat_completions(messages=[{"role": "user", "content": "x"}])
    assert "replayt doctor" in str(excinfo.value)


def test_openai_compat_401_with_api_key_hints_key_or_url() -> None:
    client = OpenAICompatClient(
        LLMSettings(api_key="not-empty", base_url="http://127.0.0.1:9999/v1"),
        http_client=_FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(b"{}", status=401))),
    )
    with pytest.raises(RuntimeError, match="401 Unauthorized") as excinfo:
        client.chat_completions(messages=[{"role": "user", "content": "x"}])
    assert "OPENAI_API_KEY" in str(excinfo.value)
    assert "unset" not in str(excinfo.value).lower()


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


def test_openai_compat_merges_extra_body_into_payload() -> None:
    body = b'{"choices":[{"message":{"content":"{}"}}]}'
    fake_http = _FakeHTTPClient(lambda *a, **k: _stream_cm(_FakeStreamResp(body)))
    client = OpenAICompatClient(
        LLMSettings(api_key=None, base_url="http://127.0.0.1:9999/v1", extra_body={"provider_hint": "base"}),
        http_client=fake_http,
    )
    client.chat_completions(
        messages=[{"role": "user", "content": "x"}],
        extra_body={"reasoning": {"effort": "low"}},
    )
    kwargs = fake_http.calls[0][1]
    assert kwargs["json"]["provider_hint"] == "base"
    assert kwargs["json"]["reasoning"] == {"effort": "low"}


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
