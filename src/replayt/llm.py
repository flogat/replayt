from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

import httpx
from pydantic import BaseModel

from replayt.types import LogMode

T = TypeVar("T", bound=BaseModel)


def _extract_json_object(text: str) -> str:
    text = text.strip()
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return text[idx : idx + end]
    raise ValueError("No JSON object found in model response")


@dataclass
class LLMSettings:
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 120.0
    max_tokens: int | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    http_retries: int = 0

    _provider_presets: ClassVar[dict[str, tuple[str, str]]] = {
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
        "ollama": ("http://127.0.0.1:11434/v1", "llama3.2"),
        "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
        "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.1-8B-Instruct-Turbo"),
        "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
        # Anthropic native HTTP is not OpenAI-compat; use a gateway or SDK-in-step (replayt_examples README).
        "anthropic": (
            "https://api.anthropic.com/v1",
            "claude-3-5-sonnet-20241022",
        ),
    }

    @classmethod
    def for_provider(cls, name: str, *, api_key: str | None = None, model: str | None = None) -> LLMSettings:
        """Build settings from a named OpenAI-*compatible* preset (URLs only; some vendors need a compat proxy).

        Presets: ``openai``, ``ollama``, ``groq``, ``together``, ``openrouter``, ``anthropic`` (set
        ``OPENAI_BASE_URL`` to your Anthropic OpenAI-compat gateway if the default host does not speak
        ``/chat/completions``).
        """

        key = name.strip().lower()
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
        preset_base = "https://api.openai.com/v1"
        preset_model = "gpt-4o-mini"
        if provider:
            preset = cls.for_provider(provider)
            preset_base = preset.base_url
            preset_model = preset.model
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL", preset_base),
            model=os.environ.get("REPLAYT_MODEL", preset_model),
        )


_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0


class OpenAICompatClient:
    """Minimal chat.completions client for OpenAI-compatible servers."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings.from_env()
        self._http: httpx.Client | None = None

    @property
    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.settings.timeout_seconds)
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

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                r = self._client.post(url, json=payload, headers=headers, timeout=timeout)
                if r.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                    retry_after = r.headers.get("retry-after")
                    try:
                        delay = float(retry_after) if retry_after else _RETRY_BASE_DELAY
                    except (ValueError, TypeError):
                        delay = _RETRY_BASE_DELAY
                    delay = min(delay * (2**attempt), _RETRY_MAX_DELAY)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                try:
                    return r.json()
                except json.JSONDecodeError as exc:
                    preview = (r.text or "")[:500]
                    raise RuntimeError(
                        f"Chat completions response was not valid JSON (HTTP {r.status_code}): {exc}; "
                        f"body preview: {preview!r}"
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
        eff_temp = float(d["temperature"]) if "temperature" in d else temperature
        eff_max = max_tokens if max_tokens is not None else d.get("max_tokens")
        if eff_max is None:
            eff_max = base.max_tokens
        eff_timeout = timeout_seconds if timeout_seconds is not None else d.get("timeout_seconds")
        if eff_timeout is None:
            eff_timeout = base.timeout_seconds
        hdrs: dict[str, str] = {}
        hdrs.update(dict(base.extra_headers or {}))
        hdrs.update(dict(d.get("extra_headers") or {}))
        hdrs.update(extra_headers or {})
        effective = {
            "model": eff_model,
            "temperature": eff_temp,
            "max_tokens": eff_max,
            "timeout_seconds": eff_timeout,
            "extra_header_names": sorted(hdrs.keys()),
        }
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
        max_tok = int(eff_max) if isinstance(eff_max, int) else None
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
        obj = json.loads(_extract_json_object(text))
        result = model_type.model_validate(obj)
        self._emit(
            "structured_output",
            {"state": self._state_getter(), "schema_name": model_type.__name__, "data": result.model_dump()},
        )
        return result
