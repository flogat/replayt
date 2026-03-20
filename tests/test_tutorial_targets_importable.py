from __future__ import annotations

import importlib
import re
from pathlib import Path


def test_tutorial_readme_workflow_targets_importable() -> None:
    """Every ``replayt_examples.*:wf`` cited in the tutorial README must import."""

    readme = Path(__file__).resolve().parents[1] / "src" / "replayt_examples" / "README.md"
    text = readme.read_text(encoding="utf-8")
    targets = sorted(set(re.findall(r"replayt_examples\.[a-z0-9_]+:wf", text)))
    assert targets, "expected at least one replayt_examples.*:wf in tutorial README"
    for ref in targets:
        mod_name, _, attr = ref.partition(":")
        assert attr == "wf", ref
        mod = importlib.import_module(mod_name)
        wf = getattr(mod, "wf")
        assert wf.name and wf.version is not None
