"""Tests for skill-loop argv template contract (version JSON)."""

from __future__ import annotations

from replayt.cli.skill_loop_placeholders import (
    SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA,
    build_skill_loop_placeholder_contract,
)


def test_build_skill_loop_placeholder_contract_shape() -> None:
    data = build_skill_loop_placeholder_contract()
    assert data["schema"] == SKILL_LOOP_PLACEHOLDER_CONTRACT_SCHEMA
    assert isinstance(data["notes"], str) and data["notes"]
    skill = data["skill_command_placeholders"]
    check = data["check_command_placeholders"]
    assert [r["name"] for r in skill] == sorted(r["name"] for r in skill)
    assert [r["name"] for r in check] == sorted(r["name"] for r in check)
    names = {r["name"] for r in skill}
    assert names == {
        "invocation_file",
        "invocation_rel",
        "iteration",
        "log_file",
        "log_rel",
        "max_iterations",
        "pipeline_sha256",
        "prompt_file",
        "prompt_rel",
        "repo",
        "run_dir",
        "run_dir_rel",
        "run_stamp",
        "skill",
        "skill_command_sha256",
        "skill_path",
        "skill_root",
        "step_index",
        "step_total",
        "task",
        "task_sha256",
    }
    assert {r["name"] for r in check} == {"iteration", "repo"}
    for row in skill + check:
        assert row["description"].strip()
