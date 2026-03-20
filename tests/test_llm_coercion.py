from __future__ import annotations

import pytest

from replayt.llm_coercion import coerce_max_tokens_for_api, coerce_temperature, coerce_timeout_seconds


def test_coerce_max_tokens_float_whole() -> None:
    assert coerce_max_tokens_for_api(4096.0) == 4096


def test_coerce_max_tokens_string() -> None:
    assert coerce_max_tokens_for_api(" 128 ") == 128


def test_coerce_max_tokens_none_and_bool() -> None:
    assert coerce_max_tokens_for_api(None) is None
    assert coerce_max_tokens_for_api(True) is None


def test_coerce_temperature_rejects_bool() -> None:
    with pytest.raises(TypeError):
        coerce_temperature(True)


def test_coerce_temperature_string() -> None:
    assert coerce_temperature("0.5", default=0.0) == 0.5


def test_coerce_timeout_seconds_string() -> None:
    assert coerce_timeout_seconds("30.5") == 30.5
