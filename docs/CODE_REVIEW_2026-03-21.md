# Deep Code Review - 2026-03-21

## Assessment

The codebase is still in solid shape structurally: the runtime, persistence, and CLI layers are separated cleanly enough that targeted fixes stay small. This pass found one confirmed high-severity robustness issue in the SQLite store and one confirmed medium-severity operator-facing issue in the JSONL read path. Both are now fixed with focused regressions, so deeper work is not required before the next patch release.

## Critical

None.

## High

- **Failed SQLite writes left the connection stuck inside an open transaction**
  - **Why it matters**
    A single insert failure could wedge the `SQLiteStore` for the rest of the process. After one failed write, later calls could fail with `cannot start a transaction within a transaction`, which breaks direct SQLite runs and SQLite mirror writes until the process exits.
  - **Evidence from the code**
    The mitigation now wraps `append_event()` in an explicit rollback path at [`src/replayt/persistence/sqlite.py#L53`](../src/replayt/persistence/sqlite.py#L53) and does the same for `append()` at [`src/replayt/persistence/sqlite.py#L77`](../src/replayt/persistence/sqlite.py#L77). The two regressions that reproduce the pre-fix failure modes are [`tests/test_sqlite_store.py#L31`](../tests/test_sqlite_store.py#L31) and [`tests/test_sqlite_store.py#L54`](../tests/test_sqlite_store.py#L54).
  - **Concrete recommendation**
    Keep every transactional write path fail-closed: if a write begins a transaction or can trigger SQLite's implicit transaction handling, rollback on every exception before re-raising. Apply the same rule to future delete or migration helpers if they grow more complex than a single happy-path statement.

## Medium

- **Read-only CLI commands created the JSONL log directory as a side effect**
  - **Why it matters**
    Commands such as `runs`, `stats`, `inspect`, `report`, and export-style reads should not mutate the filesystem just to discover that no logs exist. Creating `.replayt/runs` on read is surprising in normal use and can also turn harmless read commands into failures on read-only mounts or stricter CI sandboxes.
  - **Evidence from the code**
    `JSONLStore` now accepts an explicit creation policy at [`src/replayt/persistence/jsonl.py#L88`](../src/replayt/persistence/jsonl.py#L88), while the read-only CLI path opts out via [`src/replayt/cli/stores.py#L44`](../src/replayt/cli/stores.py#L44). The regression that proves `runs` and `stats` no longer create a missing log directory is [`tests/test_cli.py#L595`](../tests/test_cli.py#L595).
  - **Concrete recommendation**
    Keep store construction split by intent: write paths may create directories, read paths should not. If more store helpers are added later, make that distinction part of the helper API instead of relying on individual callers to remember it.

## Low

None.

## Potential concerns / assumptions

- Assumption: read-only commands should prefer "no data found" over eagerly creating the default log root. That matches operator expectations and existing CLI semantics elsewhere; keep the same rule when adding new commands.
- Assumption: rolling back the SQLite connection on all write failures is always preferable to leaving the caller to decide recovery. For this store API, that is the correct tradeoff because the class owns the connection lifecycle and callers expect the store to remain usable after an exception.

## What is good

- The persistence layer is small and well-factored, which made both fixes local instead of cascading through the runtime.
- Existing tests already covered the main store and CLI surfaces, so the new regressions could be narrow and behavior-focused.
- The `read_store()` / `open_store()` split in [`src/replayt/cli/stores.py`](../src/replayt/cli/stores.py) was already a good abstraction boundary; the fix only had to make that split stricter.

## Missing tests

- Add one more read-path regression for a command that exits non-zero on missing data, such as `inspect` or `report`, to prove it also avoids creating the log directory.
- Add a mirror-oriented regression that forces a SQLite mirror write failure through `MultiStore.append_event()` and then verifies a later mirror write succeeds with the same `SQLiteStore` instance.

## Refactoring opportunities

- A tiny transactional helper inside `SQLiteStore` would remove repeated `commit` / `rollback` structure from write methods and make future changes harder to get wrong.
- `JSONLStore` now has an intent flag. If more stores gain similar semantics, a dedicated read-only store protocol or factory would make the contract more explicit than a boolean constructor option.

## Verdict

The repository remains production-ready, but this pass exposed two real operational footguns: SQLite could get stuck after a write failure, and read-only CLI commands could mutate the log root unexpectedly. Both issues were fixed without architectural churn, and the updated tests cover the exact failure modes that mattered.

## Mitigation summary

1. **What changed**
   - **High - failed SQLite writes left the connection stuck inside an open transaction:** added rollback-on-exception handling in [`src/replayt/persistence/sqlite.py`](../src/replayt/persistence/sqlite.py) for both `append_event()` and `append()`, with regressions in [`tests/test_sqlite_store.py`](../tests/test_sqlite_store.py).
   - **Medium - read-only CLI commands created the JSONL log directory as a side effect:** added a `create` toggle to [`src/replayt/persistence/jsonl.py`](../src/replayt/persistence/jsonl.py) and switched [`src/replayt/cli/stores.py`](../src/replayt/cli/stores.py) to open JSONL stores in non-creating mode for read commands; covered by a regression in [`tests/test_cli.py`](../tests/test_cli.py).
   - Recorded the review pass and patch-release notes in [`CHANGELOG.md`](../CHANGELOG.md).

2. **Tests / checks run**
   - `python -m pytest tests/test_sqlite_store.py::test_sqlite_append_event_rolls_back_failed_transaction tests/test_sqlite_store.py::test_sqlite_append_rolls_back_failed_transaction tests/test_cli.py::test_cli_read_commands_do_not_create_missing_log_dir -q` -> passed (`3 passed`).
   - `python -m pytest tests/test_sqlite_store.py tests/test_cli.py -k "read_commands or inspect_and_replay_can_read_from_sqlite or run_with_sqlite_closes_store_after_command or resume_with_sqlite_closes_store_after_command or gc_deletes_sqlite_only_runs or gc_rejects_missing_sqlite_without_creating_database" -q` -> passed (`7 passed, 87 deselected`).

3. **Deferred mitigations**
   - None.
