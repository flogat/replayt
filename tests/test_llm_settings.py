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
