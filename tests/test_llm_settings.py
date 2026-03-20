from __future__ import annotations

import pytest

from replayt.llm import LLMSettings


def test_for_provider_ollama() -> None:
    s = LLMSettings.for_provider("ollama")
    assert "11434" in s.base_url
    assert s.model


def test_for_provider_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        LLMSettings.for_provider("nope")


def test_from_env_respects_provider(monkeypatch) -> None:
    monkeypatch.setenv("REPLAYT_PROVIDER", "groq")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    s = LLMSettings.from_env()
    assert "groq.com" in s.base_url


def test_from_env_default_uses_openrouter(monkeypatch) -> None:
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    s = LLMSettings.from_env()
    assert "openrouter.ai" in s.base_url
    assert s.model == "anthropic/claude-sonnet-4.6"


def test_from_env_rejects_non_integer_max_response_bytes(monkeypatch) -> None:
    monkeypatch.setenv("REPLAYT_LLM_MAX_RESPONSE_BYTES", "not-a-number")
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="REPLAYT_LLM_MAX_RESPONSE_BYTES"):
        LLMSettings.from_env()


def test_from_env_rejects_non_integer_max_schema_chars(monkeypatch) -> None:
    monkeypatch.setenv("REPLAYT_LLM_MAX_SCHEMA_CHARS", "oops")
    monkeypatch.delenv("REPLAYT_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="REPLAYT_LLM_MAX_SCHEMA_CHARS"):
        LLMSettings.from_env()
