"""Helpers for deterministic tests: mock LLM responses and assert on run logs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from replayt.llm import LLMSettings, OpenAICompatClient
from replayt.persistence.base import EventStore
from replayt.runner import Runner, RunResult
from replayt.types import LogMode
from replayt.workflow import Workflow


class MockLLMClient(OpenAICompatClient):
    """Queue fake ``/chat/completions`` JSON payloads (no network).

    Use :meth:`enqueue` with the assistant message **content** string (for ``complete_text`` /
    ``parse``, the content must be valid JSON when using :meth:`~replayt.llm.LLMBridge.parse`).
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        super().__init__(settings or LLMSettings(api_key="test"))
        self._responses: list[dict[str, Any]] = []

    def enqueue(self, content: str, *, usage: dict[str, Any] | None = None) -> None:
        self._responses.append(
            {
                "choices": [{"message": {"content": content}}],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }
        )

    def clear(self) -> None:
        self._responses.clear()

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
        _ = (messages, model, temperature, max_tokens, timeout_seconds, extra_headers, response_format)
        if not self._responses:
            raise RuntimeError("MockLLMClient: no queued response; call .enqueue(...) before running the workflow")
        return self._responses.pop(0)


def run_with_mock(
    wf: Workflow,
    store: EventStore,
    mock: MockLLMClient,
    *,
    inputs: dict[str, Any] | None = None,
    run_id: str | None = None,
    resume: bool = False,
    log_mode: LogMode = LogMode.redacted,
) -> RunResult:
    """Run *wf* with a :class:`MockLLMClient` instead of calling a real provider."""

    runner = Runner(wf, store, log_mode=log_mode, llm_client=mock)
    return runner.run(inputs=inputs, run_id=run_id, resume=resume)


def assert_events(
    store: EventStore,
    run_id: str,
    event_type: str,
    *,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Return events of *event_type* for *run_id*; raise ``AssertionError`` if too few match *predicate*."""

    raw = store.load_events(run_id)
    matching = [e for e in raw if e.get("type") == event_type]
    if predicate is not None:
        matching = [e for e in matching if predicate(e)]
    if len(matching) < min_count:
        raise AssertionError(
            f"expected at least {min_count} events of type {event_type!r}, found {len(matching)} (run_id={run_id!r})"
        )
    return matching
