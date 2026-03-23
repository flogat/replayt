"""Tests for package version metadata exposed to downstreams."""

from __future__ import annotations

import re

import replayt


def test_version_tuple_matches_leading_semver_prefix() -> None:
    prefix = re.match(r"^(\d+)\.(\d+)\.(\d+)", replayt.__version__.strip())
    assert prefix is not None
    assert replayt.__version_tuple__ == (
        int(prefix.group(1)),
        int(prefix.group(2)),
        int(prefix.group(3)),
    )


def test_public_api_all_exported_names_exist() -> None:
    """``__all__`` must match importable symbols (design principles: explicit, small surface)."""

    for name in replayt.__all__:
        assert hasattr(replayt, name), f"replayt.__all__ lists missing name {name!r}"
        getattr(replayt, name)
