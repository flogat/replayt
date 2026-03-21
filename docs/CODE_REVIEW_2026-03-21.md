# Deep Code Review - 2026-03-21

## Overall assessment

The repository is in good shape for its core workflow, persistence, and CLI execution paths. This review pass found one confirmed operator-facing correctness issue in the SQLite read path: read-only commands could create a brand-new empty database when the requested `--sqlite` file did not exist, which mutates the workspace and obscures the original configuration mistake. That behavior is now fixed in-repo, with targeted CLI regressions plus a full local suite run (`python -m pytest -q` -> `206 passed, 3 skipped`).

## Critical

None.

## High

None.

## Medium

- **Read-only SQLite commands created empty databases on missing paths**
  - **Why it matters**
    Read-oriented commands should not mutate the filesystem. Before this fix, `inspect`, `replay`, `runs`, `stats`, `report`, `report-diff`, `export-run`, `bundle-export`, and `gc --sqlite ...` could silently create an empty SQLite file when the operator pointed at a missing database. That both hid the real problem and left misleading artifacts behind.
  - **Evidence from the code**
    [`src/replayt/cli/stores.py`](../src/replayt/cli/stores.py) opened read paths with `SQLiteStore(sqlite)` directly, and [`src/replayt/cli/commands/inspect.py`](../src/replayt/cli/commands/inspect.py) did the same inside `cmd_gc()`. `SQLiteStore.__init__()` creates parent directories and initializes the database, so a missing file was treated as "create one now" rather than "report a missing store".
  - **Concrete recommendation**
    Fail fast before opening SQLite in read-only code paths: check `Path.is_file()`, print a clear operator message, exit with code `2`, and add regressions proving the missing database is not created as a side effect. That mitigation is now implemented in [`src/replayt/cli/stores.py`](../src/replayt/cli/stores.py), [`src/replayt/cli/commands/inspect.py`](../src/replayt/cli/commands/inspect.py), and [`tests/test_cli.py`](../tests/test_cli.py).

## Low

None.

## Potential concerns / assumptions

- Assumption: the `anthropic` provider preset is intended only for OpenAI-compatible Anthropic gateways, not Anthropic's native API. [`src/replayt/llm.py`](../src/replayt/llm.py) still points that preset at `https://api.anthropic.com/v1` while `OpenAICompatClient` always calls `/chat/completions`; the surrounding comments suggest that is deliberate, but I did not validate it against a live endpoint in this pass.
- Assumption: JSONL remains the primary source of truth for local runs. `read_store()` now fails closed on missing SQLite paths, which is the safer CLI behavior, but teams that want automatic fallback to JSONL would need that policy choice documented explicitly rather than inferred.

## What is good

- The run engine still has clear and auditable terminal behavior: `run_failed`, `run_paused`, and `run_completed` emission is explicit and easy to reason about.
- The timeout wrapper fixes already in the worktree meaningfully improved observability for parent-side timeouts and local `src/` checkouts.
- Persistence code keeps the operational model simple. JSONL and SQLite behavior is concrete, with explicit sequencing and corruption handling instead of broad retry loops.
- CLI coverage is strong for a small package. The review fix here was cheap to lock down because the command layer is already testable with `CliRunner`.

## Missing tests

- A single shared regression around every read-only SQLite command that uses `read_store()` would make the fail-fast contract more obvious than relying on one representative command.
- A live-provider smoke test for the documented non-default provider presets, especially the Anthropic compatibility guidance in [`src/replayt/llm.py`](../src/replayt/llm.py).
- A subprocess integration test where a timeout-wrapped child writes partial run state before the parent appends `run_interrupted`, so the final event ordering is validated end to end rather than via monkeypatch.

## Refactoring opportunities

- Split legacy compatibility helpers out of [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py); the file still carries superseded helper variants that make current report behavior harder to scan than necessary.
- Consider a small read-only SQLite helper or mode flag on `SQLiteStore` so "open existing DB" and "create writable DB" are distinct operations instead of being enforced only by CLI-side guard code.
- Factor common CLI store-opening error handling into one place if more read-path validation rules are added later.

## Summary verdict

The codebase is production-ready for its main replay workflow, and the confirmed defect from this pass was narrow and operational rather than architectural. With the SQLite read-path mutation fixed and covered by regression tests, the remaining risks are mostly integration assumptions and a few maintainability cleanups, not blockers in the current repository state.
