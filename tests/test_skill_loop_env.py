from __future__ import annotations

from replayt.cli.skill_loop_env import (
    SKILL_LOOP_ENV_CONTRACT_SCHEMA,
    SKILL_LOOP_FIX_INJECTED_ENV_KEYS,
    SKILL_LOOP_MAIN_INJECTED_ENV_KEYS,
    build_skill_loop_env_contract,
)


def test_skill_loop_fix_injected_keys_subset_of_main() -> None:
    main = set(SKILL_LOOP_MAIN_INJECTED_ENV_KEYS)
    fix = set(SKILL_LOOP_FIX_INJECTED_ENV_KEYS)
    assert fix <= main
    assert "SKILL_PATH" in main and "SKILL_PATH" not in fix
    assert "SKILL_REQUESTED_NAME" in main and "SKILL_REQUESTED_NAME" not in fix


def test_build_skill_loop_env_contract_shape() -> None:
    data = build_skill_loop_env_contract()
    assert data["schema"] == SKILL_LOOP_ENV_CONTRACT_SCHEMA
    main_rows = data["main_injected_env"]
    fix_rows = data["fix_injected_env"]
    assert [r["name"] for r in main_rows] == list(SKILL_LOOP_MAIN_INJECTED_ENV_KEYS)
    assert [r["name"] for r in fix_rows] == list(SKILL_LOOP_FIX_INJECTED_ENV_KEYS)
    for row in main_rows + fix_rows:
        assert row["description"].strip()
