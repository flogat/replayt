# Release inventory (since `v0.2.0`)

Baseline tag: **`v0.2.0`** → commit `6a06bc9` (“bump version to 0.2.0”).  
Everything below is on the first-parent line from that tag to `HEAD` (as of the last inventory refresh). Use `git log v0.2.0..HEAD --reverse` to reproduce the sequence.

## Commit ledger

| Commit   | Summary | Primary themes |
| -------- | ------- | -------------- |
| `8ceda2c` | Harden security, fix bugs, improve docs for 0.2.0 | Security (XSS, safe YAML format), LLM client pooling + retries, MultiStore mirrors, templates, CHANGELOG / CONTRIBUTING |
| `c415ea6` | Critical bugs, resource leak, robustness (code review) | CLI tool events (`name` / `arguments`), YAML scaffold `next`, Runner + httpx lifecycle, snapshot deep copy, `diff --sqlite`, MultiStore.append, tests |
| `cf3879f` | Remove AI-slop patterns from README, DEMO, examples | Documentation tone |
| `2b46cc3` | Animated SVG demos (run / inspect / replay, approval, debug, comparison) | Docs / UX, examples README |
| `b47852b` | Fix clip-path so replay command text is visible | Docs (SVG) |
| `0066209` | Harden runner, SQLite, CLI, persistence | Runner (approvals, snapshots), SQLite WAL + context manager, JSONL Windows locking, MultiStore callbacks, LLM Retry-After, DryRun schema, notebook Mermaid IDs, tests |
| `98b01cb` | Hero demo: refund story + annotations | Docs (SVG) |
| `3b9d371` | Quickstart, scope split, README onboarding, Beta classifier | Docs site map, PyPI Beta, CONTRIBUTING |
| `a93f07a` | GTM-style doc split + INSTALL / CLI / CONFIG / COMPARISON | New doc files, JSONL tail recovery, MultiStore, runner/YAML/CLI/report, cast asset |
| `fb8f94c` | **feat! v0.3.0** — `replayt_examples` rename + doc overhaul | **Breaking** package rename, PRODUCTION / RECIPES, Cursor skills, CLI / types / LLM / tests |
| `59d5f38` | Seal, runner hooks, CI changelog gate, try / ci / report / dry-check | `replayt seal`, `before_step` / `after_step`, `try` / `ci`, dry-check, stakeholder report, workflow meta + LLM experiment, CI gate + tests |
| `7f31743` | Export bundles, report-diff, run metadata, log dir env / subdir | `export-run` tarball + schema, report-diff HTML, `REPLAYT_LOG_DIR`, `--log-subdir`, `--metadata-json`, run-meta filters, state validation, tutorial LangGraph note |
| `f4a676a` | Split Typer app into modules, LLM coercion, CI artifacts | `cli/commands/*`, `llm_coercion`, `ci_artifacts`, `validation`, stores/targets/run_support, approval id string storage, expanded tests + docs |

## Thematic rollup

1. **Breaking:** Tutorial package **`examples` → `replayt_examples`**; CLI targets and docs must use the new module path (`fb8f94c`).
2. **CLI surface:** Modular command layout (`f4a676a`); `validate` / `run --dry-check` JSON; `try`, `ci`, `seal`, export/report-diff, doctor, init, bundle flows (`59d5f38`, `7f31743`, `f4a676a`); log directory and metadata ergonomics (`7f31743`).
3. **Runner & workflow:** Hooks, approval semantics, experiment metadata, YAML graph inference, safer context snapshots (`59d5f38`, `0066209`, `a93f07a`, `c415ea6`).
4. **Persistence:** SQLite WAL and lifecycle, JSONL locking and tail recovery, MultiStore strictness and error handling (`0066209`, `a93f07a`, `c415ea6`, plus follow-up items recorded in the changelog **Unreleased** / **0.3.0** bullets).
5. **LLM:** Coercion helpers, streaming and size limits, schema parsing guards, retries and env validation (across `8ceda2c`, `0066209`, `a93f07a`, `f4a676a` and changelog-documented refinements).
6. **CI & repo hygiene:** Changelog gate when protected paths change (`59d5f38`); tutorial import tests; artifact helpers (`f4a676a`).
7. **Documentation & narrative:** Large doc set split (INSTALL, CLI, CONFIG, COMPARISON, PATTERNS, SCOPE, QUICKSTART, PRODUCTION, RECIPES), README refocus, four animated demos + fixes (`3b9d371`, `a93f07a`, `fb8f94c`, SVG commits).

## How this relates to `CHANGELOG.md`

- **`## 0.2.0`** in the changelog corresponds to the tagged release line; **`8ceda2c`** landed *after* tag `v0.2.0` but documents the same “0.2.0 hardening” themes (release notes often trail the tag by one commit on active branches).
- **`## 0.3.0`** aggregates user-visible outcomes of `fb8f94c` … `f4a676a` (and tightly related doc/fix commits before the breaking rename where they shipped together).
- **`## Unreleased`** should hold only changes **after** the last changelog “release” edit that are not yet tied to a version bump.

Refresh this file when you cut a new tag (e.g. `v0.3.0`) by changing the baseline in the title and running `git log <new-tag>..HEAD`.
