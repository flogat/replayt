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


def test_for_provider_openai_uses_openai_model_slug() -> None:
    s = LLMSettings.for_provider("openai")
    assert s.base_url == "https://api.openai.com/v1"
    assert s.model == "gpt-4o-mini"


def test_for_provider_anthropic_requires_gateway() -> None:
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        LLMSettings.for_provider("anthropic")


def test_from_env_anthropic_requires_gateway(monkeypatch) -> None:
    monkeypatch.setenv("REPLAYT_PROVIDER", "anthropic")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        LLMSettings.from_env()


def test_from_env_anthropic_uses_gateway_override(monkeypatch) -> None:
    monkeypatch.setenv("REPLAYT_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.delenv("REPLAYT_MODEL", raising=False)
    s = LLMSettings.from_env()
    assert s.base_url == "https://gateway.example/v1"
    assert s.model == LLMSettings.anthropic_gateway_model


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
