from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "check_changelog_if_needed.py"
    spec = importlib.util.spec_from_file_location("check_changelog_if_needed", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_is_protected_path() -> None:
    gate = _load_script()
    assert gate.is_protected_path("src/replayt/runner.py")
    assert gate.is_protected_path("src/replayt_examples/foo.py")
    assert gate.is_protected_path("docs/RUN_LOG_SCHEMA.md")
    assert not gate.is_protected_path("tests/test_runner.py")
    assert not gate.is_protected_path("README.md")


def test_need_changelog_update() -> None:
    gate = _load_script()
    assert not gate.need_changelog_update(["tests/test_x.py", "README.md"])
    assert not gate.need_changelog_update(["src/replayt/foo.py", "CHANGELOG.md"])
    assert gate.need_changelog_update(["src/replayt/foo.py"])
    assert gate.need_changelog_update(["src/replayt_examples/x.py", "docs/foo.md"])
