from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from replayt.types import LogMode

T = TypeVar("T", bound=BaseModel)


def _extract_json_object(text: str) -> str:
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("No JSON object found in model response")
    return m.group(0)


@dataclass
class LLMSettings:
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> LLMSettings:
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("REPLAYT_MODEL", "gpt-4o-mini"),
        )


class OpenAICompatClient:
    """Minimal chat.completions client for OpenAI-compatible servers."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings.from_env()

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.settings.timeout_seconds) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()


class LLMBridge:
    """Per-run LLM helper that emits log events via callback."""

    def __init__(
        self,
        *,
        emit: Callable[[str, dict[str, Any]], None],
        client: OpenAICompatClient,
        log_mode: LogMode,
        state_getter: Callable[[], str | None],
    ) -> None:
        self._emit = emit
        self._client = client
        self._log_mode = log_mode
        self._state_getter = state_getter

    def complete_text(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        state = self._state_getter()
        m = model or self._client.settings.model
        req_payload: dict[str, Any] = {"state": state, "model": m}
        if self._log_mode == LogMode.redacted:
            req_payload["messages_summary"] = {
                "count": len(messages),
                "roles": [msg.get("role") for msg in messages],
            }
        else:
            req_payload["messages"] = messages
        self._emit("llm_request", req_payload)

        t0 = time.perf_counter()
        data = self._client.chat_completions(
            messages=messages,
            model=model,
            temperature=temperature,
        )
        dt_ms = int((time.perf_counter() - t0) * 1000)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        usage = data.get("usage")
        resp_payload: dict[str, Any] = {
            "state": state,
            "model": m,
            "latency_ms": dt_ms,
            "usage": usage,
        }
        if self._log_mode == LogMode.redacted:
            resp_payload["content_preview"] = content[:800]
        else:
            resp_payload["content"] = content
        self._emit("llm_response", resp_payload)
        return content

    def parse(
        self,
        model_type: type[T],
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.0,
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
        )
        obj = json.loads(_extract_json_object(text))
        result = model_type.model_validate(obj)
        self._emit(
            "structured_output",
            {"state": self._state_getter(), "schema_name": model_type.__name__, "data": result.model_dump()},
        )
        return result
