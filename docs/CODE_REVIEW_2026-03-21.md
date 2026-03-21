# Deep Code Review - 2026-03-21

## Assessment

The repository is in good shape for its core workflow, persistence, and CLI execution paths. This pass found one confirmed operator-facing correctness issue in provider configuration and one confirmed documentation mismatch around mirror consistency. Both are now fixed in-repo, and the current workspace passes `python -m pytest -q` with `211 passed, 3 skipped`.

## Critical

None.

## High

None.

## Medium

- **`REPLAYT_PROVIDER=anthropic` defaulted to an unusable host for the OpenAI-compatible client**
  - **Why it matters**
    `OpenAICompatClient` always calls `/chat/completions`. Pointing it at `https://api.anthropic.com/v1` guarantees a bad endpoint unless the operator separately supplies an OpenAI-compatible gateway. That is a configuration trap: the documented preset looked valid but failed only at runtime.
  - **Evidence from the code**
    Before this fix, [`src/replayt/llm.py`](../src/replayt/llm.py) included an `anthropic` preset whose base URL was Anthropic's native host, while the same module's client hard-coded OpenAI-compatible `/chat/completions` requests. The previous review note in this file treated that as an assumption; the code path confirms it.
  - **Concrete recommendation**
    Fail fast instead of shipping a broken preset. That mitigation is now implemented in [`src/replayt/llm.py`](../src/replayt/llm.py): `LLMSettings.for_provider("anthropic")` raises with guidance, `LLMSettings.from_env()` requires `OPENAI_BASE_URL` for that provider, and [`src/replayt/cli/commands/doctor.py`](../src/replayt/cli/commands/doctor.py) reports the misconfiguration cleanly. Regression coverage lives in [`tests/test_llm_settings.py`](../tests/test_llm_settings.py) and [`tests/test_cli.py`](../tests/test_cli.py).

## Low

- **`strict_mirror` docs overstated the consistency guarantee**
  - **Why it matters**
    Operators reading the docs could believe `strict_mirror = true` provides cross-store atomicity. It does not. The primary JSONL write happens before the mirror append, so a mirror failure can still leave JSONL ahead of SQLite even though the run aborts loudly.
  - **Evidence from the code**
    [`src/replayt/persistence/multi.py`](../src/replayt/persistence/multi.py) writes to the primary first, then mirrors. [`tests/test_multi_store.py`](../tests/test_multi_store.py) already locks in that behavior with `test_multi_store_strict_mirror_raises_after_primary_write`.
  - **Concrete recommendation**
    Document the actual guarantee precisely: strict mode fails loudly but does not make the write atomic across stores. That wording is now corrected in [`src/replayt/persistence/multi.py`](../src/replayt/persistence/multi.py), [`docs/CONFIG.md`](CONFIG.md), and [`docs/PRODUCTION.md`](PRODUCTION.md).

## Potential concerns / assumptions

- Assumption: JSONL remains the primary source of truth for local runs. The current implementation and tests strongly imply that, especially in mirror-failure scenarios, but product-level operator guidance should continue to say so plainly.
- Assumption: teams using Anthropic through gateways will set `OPENAI_BASE_URL` deliberately rather than expecting replayt to infer a compatibility layer. The new fail-fast behavior is safer, but it moves that choice from "surprising runtime 404" to "explicit startup validation."

## Strengths

- The run engine still has clear and auditable terminal behavior: `run_failed`, `run_paused`, and `run_completed` emission is explicit and easy to reason about.
- Persistence behavior is concrete rather than hand-wavy. Sequence allocation, corruption handling, and mirror failure paths are testable and visible.
- CLI coverage remains strong for a small package. Both issues from this pass were cheap to lock down with targeted regressions because the command layer and settings layer are already testable.

## Missing tests

- A live-provider smoke test for documented non-default provider paths would catch compatibility regressions earlier than unit tests alone.
- A focused integration test around mirror repair or reconciliation guidance would help document the operational story after `strict_mirror` failures.
- A subprocess integration test where a timeout-wrapped child writes partial run state before the parent appends `run_interrupted`, so final event ordering is validated end to end rather than via monkeypatch.

## Refactoring opportunities

- Split "provider preset" selection from "transport contract" selection more explicitly in [`src/replayt/llm.py`](../src/replayt/llm.py); today they are still coupled through one settings object.
- Consider a read-only SQLite open mode or helper so "must already exist" versus "create writable database" is enforced below the CLI layer too.
- Factor shared operator-facing diagnostics in the CLI so `doctor`, read-only store opening, and similar validation paths reuse one vocabulary for configuration failures.

## Verdict

The codebase is production-ready for its main replay workflow, and the issues from this pass were narrow enough to fix without destabilizing the runtime. After the Anthropic preset hardening and the mirror-consistency doc correction, the main residual risks are integration assumptions and some maintainability cleanup, not blockers in the current repository state.
