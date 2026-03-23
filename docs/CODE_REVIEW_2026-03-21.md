# Deep Code Review - 2026-03-21

## Assessment

The runtime, CLI, config resolution, and persistence layers are clearly separated, so review fixes stayed local. This pass found two confirmed high-severity issues in LLM gateway handling and audit-surface hygiene, plus one confirmed medium-severity SQLite read-path problem. All three are now fixed with targeted regressions, so this review did not uncover a larger remediation project before the next patch release.

## Critical

None.

## High

- **Secret-bearing `OPENAI_BASE_URL` values leaked into runtime and operator-facing output**
  - **Why it matters**
    A credential embedded in `OPENAI_BASE_URL` userinfo or query parameters could be persisted in `run_started` / `llm_request` logs and echoed by `replayt config` / `replayt doctor`. That is both an audit-surface leak and an avoidable secret-handling failure.
  - **Evidence from the code**
    Runtime snapshots now sanitize logged LLM base URLs at [`src/replayt/runner.py#L255`](../src/replayt/runner.py#L255), per-call `effective.base_url` is sanitized at [`src/replayt/llm.py#L593`](../src/replayt/llm.py#L593), and CLI config/doctor output now derives from sanitized values at [`src/replayt/cli/config.py#L288`](../src/replayt/cli/config.py#L288) and [`src/replayt/cli/commands/doctor.py#L156`](../src/replayt/cli/commands/doctor.py#L156). Regressions cover the helper and the persisted/operator-facing paths in [`tests/test_security.py#L142`](../tests/test_security.py#L142), [`tests/test_runner.py#L259`](../tests/test_runner.py#L259), and [`tests/test_cli.py#L5332`](../tests/test_cli.py#L5332).
  - **Concrete recommendation**
    Keep one log-safe URL helper and route every operator-facing or persisted URL through it. Raw transport URLs should stay in memory only for actual HTTP calls.

- **Custom LLM gateway `base_url` was ignored when `provider` was also set**
  - **Why it matters**
    A run configured for an OpenAI-compatible proxy or on-prem gateway could silently fall back to the provider preset host. That breaks routing expectations, weakens compliance controls, and can send traffic to the wrong service.
  - **Evidence from the code**
    `LLMBridge._merge_call()` now falls back to the resolved client/base settings `base_url` before provider-preset resolution at [`src/replayt/llm.py#L508`](../src/replayt/llm.py#L508). The regression in [`tests/test_runner.py#L259`](../tests/test_runner.py#L259) proves both `run_started.runtime.llm.base_url` and the `llm_request` effective payload preserve the configured gateway.
  - **Concrete recommendation**
    Preserve explicit transport fields from resolved settings first, then fill only missing values from provider presets. Keep one focused regression for `provider + custom base_url` because that combination is easy to break in future refactors.

## Medium

- **Read-only `--sqlite` CLI commands opened SQLite in writable/init mode**
  - **Why it matters**
    `inspect`, `report`, `runs`, and `stats` should not attempt WAL setup or schema initialization against a database they only mean to read. That creates avoidable side effects and can fail on read-only mounts or tighter production permissions.
  - **Evidence from the code**
    `SQLiteStore` now supports an explicit read-only mode and blocks writes in that mode at [`src/replayt/persistence/sqlite.py#L19`](../src/replayt/persistence/sqlite.py#L19) and [`src/replayt/persistence/sqlite.py#L54`](../src/replayt/persistence/sqlite.py#L54), while the CLI read path now opts into that mode at [`src/replayt/cli/stores.py#L44`](../src/replayt/cli/stores.py#L44). Regressions land in [`tests/test_sqlite_store.py#L125`](../tests/test_sqlite_store.py#L125) and [`tests/test_cli.py#L5310`](../tests/test_cli.py#L5310).
  - **Concrete recommendation**
    Keep separate read/write store construction paths anywhere initialization code can mutate the backend. Read helpers should never depend on a writable constructor behaving politely.

## Low

None.

## Potential concerns / assumptions

- Assumption: sanitizing operator-facing and persisted base URLs is sufficient because raw URLs are still needed for actual HTTP traffic. If future diagnostics surface raw HTTP exception strings, sanitize those too before echoing them.
- Assumption: SQLite URI read-only mode is acceptable for supported Python/SQLite builds. If older Windows or embedded SQLite builds behave differently, add a compatibility smoke test around URI-based read-only opens.

## Strengths

- The trust-boundary code already had a clear vocabulary, so the URL-sanitization fix extended the existing design instead of bolting on a second security layer.
- `resolve_llm_settings(...)`, `Runner._runtime_snapshot()`, and `LLMBridge._merge_call()` are factored tightly enough that the gateway fixes stayed localized.
- The CLI already distinguished `open_store()` from `read_store()`, which made the SQLite read-only hardening straightforward.

## Missing tests

- Add a `doctor` connectivity-failure regression so HTTP exception text never echoes raw credential-bearing URLs.
- Add a filesystem-level SQLite read-only smoke test, if a portable fixture is available, so the `mode=ro` path is exercised beyond constructor-level behavior.

## Refactoring opportunities

- Introduce a small typed "resolved LLM endpoint" view carrying both raw and log-safe URL fields so call sites stop deciding ad hoc which representation to use.
- If more read/write-specific SQLite behavior accumulates, split `SQLiteStore` into dedicated reader/writer wrappers instead of growing the boolean `read_only` flag.

## Verdict

Within its stated scope, the tree is fine to ship. This pass still found three operational problems: secret handling, gateway correctness, and read-only SQLite from the CLI. Fixes are small and covered by focused regressions; nothing here suggests a larger redesign.
