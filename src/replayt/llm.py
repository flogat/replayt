from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from replayt.llm_coercion import (
    coerce_max_tokens_for_api,
    coerce_temperature,
    coerce_timeout_seconds,
)
from replayt.types import LogMode

T = TypeVar("T", bound=BaseModel)


class _HTTPStreamClient(Protocol):
    def stream(self, method: str, url: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


# Cap `{` probes so pathological multi-megabyte text cannot burn CPU in raw_decode attempts.
_MAX_JSON_OBJECT_BRACE_STARTS = 50_000


def _extract_json_object(text: str, *, max_brace_starts: int = _MAX_JSON_OBJECT_BRACE_STARTS) -> str:
    """Parse JSON object spans from *text* and pick a single ``{...}`` result.

    Nested objects produce multiple valid spans (inner and outer). Spans **strictly contained**
    in another dict span are dropped. If more than one span remains (e.g. two sibling objects),
    the **last** span wins so a trailing final JSON object beats an earlier draft.
    """

    text = text.strip()
    decoder = json.JSONDecoder()
    spans: list[tuple[int, int, str]] = []
    brace_starts = 0
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        brace_starts += 1
        if brace_starts > max_brace_starts:
            raise ValueError(
                f"Too many '{{' characters to scan for a JSON object (limit {max_brace_starts}); "
                "response may be malformed or not JSON-object-shaped."
            )
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            end_idx = idx + end
            spans.append((idx, end_idx, text[idx:end_idx]))

    if not spans:
        raise ValueError(
            "No JSON object found in model response (expected a {...} object). "
            "If the model returned markdown fences, prose only, or non-object JSON, adjust the prompt "
            "or parse the text manually."
        )

    def strictly_inside(inner: tuple[int, int, str], outer: tuple[int, int, str]) -> bool:
        a0, a1, _ = inner
        b0, b1, _ = outer
        return b0 < a0 and a1 < b1

    maximal: list[tuple[int, int, str]] = []
    for sp in spans:
        if any(strictly_inside(sp, other) for other in spans):
            continue
        maximal.append(sp)
    if not maximal:
        maximal = list(spans)
    return maximal[-1][2]


@dataclass
class LLMSettings:
    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "anthropic/claude-sonnet-4.6"
    timeout_seconds: float = 120.0
    max_tokens: int | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    http_retries: int = 0
    #: Upper bound on ``LLMBridge.parse`` response text length (after ``complete_text``) before ``json.loads``.
    max_parse_response_chars: int = 4_000_000
    #: Hard cap on HTTP response body size for ``/chat/completions`` (bytes), read via streaming.
    max_response_bytes: int = 32 * 1024 * 1024
    #: Upper bound on JSON Schema text embedded in :meth:`LLMBridge.parse` system prompts.
    max_schema_json_chars: int = 250_000
    #: Default model slug when routing Anthropic traffic through an OpenAI-compatible gateway.
    anthropic_gateway_model: ClassVar[str] = "claude-3-5-sonnet-20241022"

    _provider_presets: ClassVar[dict[str, tuple[str, str]]] = {
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
        "ollama": ("http://127.0.0.1:11434/v1", "llama3.2"),
        "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
        "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.1-8B-Instruct-Turbo"),
        "openrouter": ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.6"),
    }

    @classmethod
    def _anthropic_gateway_error(cls) -> str:
        return (
            "Provider 'anthropic' requires OPENAI_BASE_URL to point at an OpenAI-compatible gateway; "
            "Anthropic's native API does not expose /chat/completions. Set OPENAI_BASE_URL explicitly "
            "or call the anthropic SDK inside a workflow step."
        )

    @classmethod
    def for_provider(cls, name: str, *, api_key: str | None = None, model: str | None = None) -> LLMSettings:
        """Build settings from a named OpenAI-*compatible* preset (URLs only; some vendors need a compat proxy).

        Presets: ``openai``, ``ollama``, ``groq``, ``together``, ``openrouter``. Anthropic's native
        API is not OpenAI-compatible; use ``OPENAI_BASE_URL`` with an OpenAI-compatible gateway or call
        Anthropic's SDK inside a workflow step.
        """

        key = name.strip().lower()
        if key == "anthropic":
            raise ValueError(cls._anthropic_gateway_error())
        if key not in cls._provider_presets:
            allowed = ", ".join(sorted(cls._provider_presets.keys()))
            raise ValueError(f"Unknown provider {name!r}; expected one of: {allowed}")
        base_url, default_model = cls._provider_presets[key]
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model or default_model,
        )

    @classmethod
    def from_env(cls) -> LLMSettings:
        provider = os.environ.get("REPLAYT_PROVIDER", "").strip().lower()
        env_base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if provider:
            if provider == "anthropic":
                if not env_base_url:
                    raise ValueError(cls._anthropic_gateway_error())
                preset_base = env_base_url
                preset_model = cls.anthropic_gateway_model
            else:
                preset = cls.for_provider(provider)
                preset_base = preset.base_url
                preset_model = preset.model
        else:
            preset_base, preset_model = cls._provider_presets["openrouter"]
        max_rb = 32 * 1024 * 1024
        raw_rb = os.environ.get("REPLAYT_LLM_MAX_RESPONSE_BYTES", "").strip()
        if raw_rb:
            try:
                max_rb = max(1024, int(raw_rb))
            except ValueError:
                raise ValueError(
                    f"REPLAYT_LLM_MAX_RESPONSE_BYTES must be an integer number of bytes, got {raw_rb!r}"
                ) from None
        max_schema = 250_000
        raw_schema = os.environ.get("REPLAYT_LLM_MAX_SCHEMA_CHARS", "").strip()
        if raw_schema:
            try:
                max_schema = max(1024, int(raw_schema))
            except ValueError:
                raise ValueError(
                    f"REPLAYT_LLM_MAX_SCHEMA_CHARS must be a positive integer, got {raw_schema!r}"
                ) from None
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=env_base_url or preset_base,
            model=os.environ.get("REPLAYT_MODEL", preset_model),
            max_response_bytes=max_rb,
            max_schema_json_chars=max_schema,
        )


# 500 included: many gateways return it for transient upstream failures (retry-safe in practice).
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0


def _drain_stream_with_limit(response: httpx.Response, byte_limit: int) -> None:
    n = 0
    for chunk in response.iter_bytes():
        n += len(chunk)
        if n >= byte_limit:
            break


def _read_response_body_capped(response: httpx.Response, max_bytes: int) -> bytes:
    buf = bytearray()
    for chunk in response.iter_bytes():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise RuntimeError(
                f"Chat completions response body exceeds max_response_bytes ({max_bytes}); "
                "raise LLMSettings.max_response_bytes if needed."
            )
    return bytes(buf)


class OpenAICompatClient:
    """Minimal chat.completions client for OpenAI-compatible servers."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        *,
        http_client: _HTTPStreamClient | None = None,
        http_client_factory: Callable[[float], _HTTPStreamClient] | None = None,
    ) -> None:
        self.settings = settings or LLMSettings.from_env()
        self._http: _HTTPStreamClient | None = http_client
        self._http_client_factory = http_client_factory or (lambda timeout: httpx.Client(timeout=timeout))

    @property
    def _client(self) -> _HTTPStreamClient:
        if self._http is None:
            self._http = self._http_client_factory(self.settings.timeout_seconds)
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        extra_headers: dict[str, str] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        eff_max = max_tokens if max_tokens is not None else self.settings.max_tokens
        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        if eff_max is not None:
            payload["max_tokens"] = eff_max
        if response_format is not None:
            payload["response_format"] = response_format
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **(self.settings.extra_headers or {}),
            **(extra_headers or {}),
        }
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.timeout_seconds
        max_attempts = max(self.settings.http_retries + 1, 1)
        cap = self.settings.max_response_bytes
        drain_cap = min(cap, 65_536)

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                with self._client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as r:
                    if r.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                        _drain_stream_with_limit(r, drain_cap)
                        retry_after = r.headers.get("retry-after")
                        try:
                            delay = float(retry_after) if retry_after else _RETRY_BASE_DELAY
                        except (ValueError, TypeError):
                            delay = _RETRY_BASE_DELAY
                        delay = min(delay * (2**attempt), _RETRY_MAX_DELAY)
                        time.sleep(delay)
                        continue
                    r.raise_for_status()
                    cl = r.headers.get("content-length")
                    if cl is not None:
                        try:
                            if int(cl) > cap:
                                raise RuntimeError(
                                    f"Chat completions Content-Length ({cl}) exceeds max_response_bytes ({cap})"
                                )
                        except ValueError:
                            pass
                    raw = _read_response_body_capped(r, cap)
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    preview = raw[:500]
                    raise RuntimeError(
                        f"Chat completions response was not valid JSON: {exc}; body preview: {preview!r}"
                    ) from exc
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY))
                    continue
                raise
        raise last_exc  # type: ignore[misc]


class LLMBridge:
    """Per-run LLM helper that emits log events via callback."""

    def __init__(
        self,
        *,
        emit: Callable[[str, dict[str, Any]], None],
        client: OpenAICompatClient,
        log_mode: LogMode,
        state_getter: Callable[[], str | None],
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self._emit = emit
        self._client = client
        self._log_mode = log_mode
        self._state_getter = state_getter
        self._defaults = defaults or {}

    def with_settings(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        extra_headers: dict[str, str] | None = None,
        experiment: dict[str, Any] | None = None,
    ) -> LLMBridge:
        """Return a new bridge with merged per-call defaults (logged on each request as ``effective``)."""

        merged: dict[str, Any] = {**self._defaults}
        if model is not None:
            merged["model"] = model
        if temperature is not None:
            merged["temperature"] = temperature
        if timeout_seconds is not None:
            merged["timeout_seconds"] = timeout_seconds
        if max_tokens is not None:
            merged["max_tokens"] = max_tokens
        if extra_headers:
            h = dict(merged.get("extra_headers") or {})
            h.update(extra_headers)
            merged["extra_headers"] = h
        if experiment is not None:
            prev = merged.get("experiment")
            if isinstance(prev, dict):
                merged["experiment"] = {**prev, **experiment}
            else:
                merged["experiment"] = dict(experiment)
        return LLMBridge(
            emit=self._emit,
            client=self._client,
            log_mode=self._log_mode,
            state_getter=self._state_getter,
            defaults=merged,
        )

    def _merge_call(
        self,
        *,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        timeout_seconds: float | None,
        extra_headers: dict[str, str] | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        d = self._defaults
        base = self._client.settings
        eff_model = model if model is not None else (d.get("model") if d.get("model") is not None else base.model)
        if "temperature" in d:
            eff_temp = coerce_temperature(d["temperature"], default=temperature)
        else:
            eff_temp = coerce_temperature(temperature, default=0.0)
        eff_max = max_tokens if max_tokens is not None else d.get("max_tokens")
        if eff_max is None:
            eff_max = base.max_tokens
        eff_max = coerce_max_tokens_for_api(eff_max)
        eff_timeout = timeout_seconds if timeout_seconds is not None else d.get("timeout_seconds")
        if eff_timeout is None:
            eff_timeout = base.timeout_seconds
        eff_timeout = coerce_timeout_seconds(eff_timeout)
        hdrs: dict[str, str] = {}
        hdrs.update(dict(base.extra_headers or {}))
        hdrs.update(dict(d.get("extra_headers") or {}))
        hdrs.update(extra_headers or {})
        effective: dict[str, Any] = {
            "model": eff_model,
            "temperature": eff_temp,
            "max_tokens": eff_max,
            "timeout_seconds": eff_timeout,
            "extra_header_names": sorted(hdrs.keys()),
        }
        exp = d.get("experiment")
        if isinstance(exp, dict) and exp:
            effective["experiment"] = dict(exp)
        return effective, hdrs

    def complete_text(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        state = self._state_getter()
        effective, hdrs = self._merge_call(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            extra_headers=extra_headers,
        )
        eff_model = str(effective["model"])
        eff_temp = float(effective["temperature"])
        eff_max = effective["max_tokens"]
        eff_timeout = float(effective["timeout_seconds"])

        req_payload: dict[str, Any] = {"state": state, "effective": effective}
        if self._log_mode == LogMode.full:
            req_payload["messages"] = messages
        elif self._log_mode == LogMode.redacted:
            req_payload["messages_summary"] = {
                "count": len(messages),
                "roles": [msg.get("role") for msg in messages],
            }
        # structured_only: state + effective only (no message bodies or role metadata); see LogMode.structured_only
        self._emit("llm_request", req_payload)

        t0 = time.perf_counter()
        max_tok = coerce_max_tokens_for_api(eff_max)
        data = self._client.chat_completions(
            messages=messages,
            model=eff_model,
            temperature=eff_temp,
            max_tokens=max_tok,
            timeout_seconds=eff_timeout,
            extra_headers=hdrs if hdrs else None,
        )
        dt_ms = int((time.perf_counter() - t0) * 1000)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        usage = data.get("usage")
        resp_payload: dict[str, Any] = {
            "state": state,
            "model": eff_model,
            "latency_ms": dt_ms,
            "usage": usage,
            "effective": effective,
        }
        if self._log_mode == LogMode.full:
            resp_payload["content"] = content
        elif self._log_mode == LogMode.redacted:
            resp_payload["content_preview"] = content[:800]
        # structured_only: omit content and preview; structured_output events still carry validated data from parse()
        self._emit("llm_response", resp_payload)
        return content

    def parse(
        self,
        model_type: type[T],
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> T:
        schema_hint = json.dumps(model_type.model_json_schema(), ensure_ascii=False)
        cap = self._client.settings.max_schema_json_chars
        if len(schema_hint) > cap:
            raise ValueError(
                f"JSON Schema for {model_type.__name__!r} serializes to {len(schema_hint)} characters, "
                f"above max_schema_json_chars ({cap}); use a smaller model, split fields, or raise the limit "
                "on LLMSettings / env REPLAYT_LLM_MAX_SCHEMA_CHARS."
            )
        sys = (
            "You must respond with a single JSON object that validates against this JSON Schema "
            f"(return JSON only, no markdown):\n{schema_hint}"
        )
        full_messages = [{"role": "system", "content": sys}, *messages]
        text = self.complete_text(
            messages=full_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            extra_headers=extra_headers,
        )
        cap = self._client.settings.max_parse_response_chars
        if len(text) > cap:
            raise ValueError(
                f"Model response length ({len(text)} chars) exceeds max_parse_response_chars ({cap}); "
                "raise the limit on LLMSettings if needed."
            )
        obj = json.loads(_extract_json_object(text, max_brace_starts=min(_MAX_JSON_OBJECT_BRACE_STARTS, cap)))
        result = model_type.model_validate(obj)
        self._emit(
            "structured_output",
            {"state": self._state_getter(), "schema_name": model_type.__name__, "data": result.model_dump()},
        )
        return result
