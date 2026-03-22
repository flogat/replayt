from __future__ import annotations

import pytest

from replayt.version_compare import replayt_release_tuple


def test_replayt_release_tuple_simple() -> None:
    assert replayt_release_tuple("0.4.7") == (0, 4, 7)
    assert replayt_release_tuple("v1.2.3") == (1, 2, 3)
    assert replayt_release_tuple("10") == (10, 0, 0)


def test_replayt_release_tuple_prerelease_suffix() -> None:
    assert replayt_release_tuple("0.4.7-rc1") == (0, 4, 7)


def test_replayt_release_tuple_rejects_huge_numeric_segment() -> None:
    huge = "0." + "0" * 25 + ".0"
    with pytest.raises(ValueError, match="longer than"):
        replayt_release_tuple(huge)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-version", "x.y.z"],
)
def test_replayt_release_tuple_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        replayt_release_tuple(raw)
