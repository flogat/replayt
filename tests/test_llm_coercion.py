from __future__ import annotations

import pytest

from replayt.llm_coercion import (
    coerce_http_retries,
    coerce_llm_extra_body,
    coerce_llm_seed,
    coerce_llm_stop_sequences,
    coerce_max_tokens_for_api,
    coerce_openai_penalty,
    coerce_temperature,
    coerce_timeout_seconds,
    coerce_top_p,
)


def test_coerce_max_tokens_float_whole() -> None:
    assert coerce_max_tokens_for_api(4096.0) == 4096


def test_coerce_max_tokens_string() -> None:
    assert coerce_max_tokens_for_api(" 128 ") == 128


def test_coerce_max_tokens_none() -> None:
    assert coerce_max_tokens_for_api(None) is None


def test_coerce_max_tokens_rejects_bool() -> None:
    with pytest.raises(TypeError, match="max_tokens cannot be a boolean"):
        coerce_max_tokens_for_api(True)


def test_coerce_max_tokens_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_max_tokens_for_api("1e400")
    with pytest.raises(ValueError, match="finite"):
        coerce_max_tokens_for_api(float("inf"))
    with pytest.raises(ValueError, match="finite"):
        coerce_max_tokens_for_api("nan")


def test_coerce_max_tokens_rejects_bad_string() -> None:
    with pytest.raises(ValueError, match="numeric"):
        coerce_max_tokens_for_api("not-a-number")


def test_coerce_http_retries_basic() -> None:
    assert coerce_http_retries(0) == 0
    assert coerce_http_retries("3") == 3
    assert coerce_http_retries(3.0) == 3


def test_coerce_http_retries_rejects_bool() -> None:
    with pytest.raises(TypeError, match="boolean"):
        coerce_http_retries(True)


def test_coerce_http_retries_rejects_negative() -> None:
    with pytest.raises(ValueError, match=">="):
        coerce_http_retries(-1)


def test_coerce_http_retries_rejects_above_cap() -> None:
    with pytest.raises(ValueError, match="<="):
        coerce_http_retries(26)


def test_coerce_temperature_rejects_bool() -> None:
    with pytest.raises(TypeError):
        coerce_temperature(True)


def test_coerce_temperature_string() -> None:
    assert coerce_temperature("0.5", default=0.0) == 0.5
    assert coerce_temperature("2", default=0.0) == 2.0
    assert coerce_temperature("0", default=0.0) == 0.0


def test_coerce_temperature_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="between 0 and 2"):
        coerce_temperature(2.0001)
    with pytest.raises(ValueError, match="between 0 and 2"):
        coerce_temperature("-0.1")


def test_coerce_temperature_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_temperature(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        coerce_temperature(float("inf"))


def test_coerce_timeout_seconds_string() -> None:
    assert coerce_timeout_seconds("30.5") == 30.5


def test_coerce_timeout_seconds_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        coerce_timeout_seconds(0)
    with pytest.raises(ValueError, match="greater than zero"):
        coerce_timeout_seconds("-1")
    with pytest.raises(ValueError, match="greater than zero"):
        coerce_timeout_seconds("0")


def test_coerce_timeout_seconds_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        coerce_timeout_seconds(float("nan"))
    with pytest.raises(ValueError, match="greater than zero"):
        coerce_timeout_seconds(float("inf"))


def test_coerce_openai_penalty_none_and_bounds() -> None:
    assert coerce_openai_penalty(None) is None
    assert coerce_openai_penalty("-1.5") == -1.5
    assert coerce_openai_penalty(2.0) == 2.0
    with pytest.raises(ValueError, match="between -2 and 2"):
        coerce_openai_penalty(3.0)
    with pytest.raises(TypeError, match="penalty cannot be a boolean"):
        coerce_openai_penalty(True)


def test_coerce_openai_penalty_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_openai_penalty(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        coerce_openai_penalty(float("inf"))


def test_coerce_top_p_none_empty_and_bounds() -> None:
    assert coerce_top_p(None) is None
    assert coerce_top_p("") is None
    assert coerce_top_p("0.5") == 0.5
    assert coerce_top_p(1.0) == 1.0
    with pytest.raises(ValueError, match="between 0 and 1"):
        coerce_top_p(1.01)
    with pytest.raises(TypeError, match="top_p cannot be a boolean"):
        coerce_top_p(True)


def test_coerce_top_p_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_top_p(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        coerce_top_p(float("inf"))


def test_coerce_llm_stop_sequences() -> None:
    assert coerce_llm_stop_sequences(None) is None
    assert coerce_llm_stop_sequences("  END  ") == ["END"]
    assert coerce_llm_stop_sequences(["a", "  ", "b"]) == ["a", "b"]
    assert coerce_llm_stop_sequences(()) is None
    with pytest.raises(ValueError, match="at most 4"):
        coerce_llm_stop_sequences(["1", "2", "3", "4", "5"])
    with pytest.raises(TypeError, match="stop sequences must be strings"):
        coerce_llm_stop_sequences([1])
    with pytest.raises(TypeError, match="stop must be str"):
        coerce_llm_stop_sequences(123)


def test_coerce_llm_extra_body() -> None:
    assert coerce_llm_extra_body(None) is None
    assert coerce_llm_extra_body({}) is None
    assert coerce_llm_extra_body({" reasoning ": {"effort": "high"}, "tags": ("a", "b")}) == {
        "reasoning": {"effort": "high"},
        "tags": ["a", "b"],
    }
    with pytest.raises(ValueError, match="conflicts with core chat fields"):
        coerce_llm_extra_body({"model": "x"}, reserved_keys={"model"})
    with pytest.raises(TypeError, match="JSON-serializable"):
        coerce_llm_extra_body({"fn": object()})


def test_coerce_llm_seed() -> None:
    assert coerce_llm_seed(None) is None
    assert coerce_llm_seed("42") == 42
    assert coerce_llm_seed(0) == 0
    assert coerce_llm_seed(4096.0) == 4096
    with pytest.raises(TypeError, match="seed cannot be a boolean"):
        coerce_llm_seed(True)
    with pytest.raises(ValueError, match="whole number"):
        coerce_llm_seed(1.5)
