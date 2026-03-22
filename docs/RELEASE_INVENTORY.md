# Release inventory (since `v0.4.0`)

Baseline tag: **`v0.4.0`** (this release). Use `git log v0.4.0..HEAD --reverse` to list commits after the tag.

## Commit ledger (next release)

| Commit | Summary | Primary themes |
| ------ | ------- | -------------- |
| _(none yet)_ | | |

## Release 0.4.0 delta (`f4a676a` ... `3082122`)

| Commit | Summary | Primary themes |
| ------ | ------- | -------------- |
| `3082122` | feat!: OpenRouter LLM defaults, persistence/CLI hardening, docs rollup | **Breaking:** unset provider -> OpenRouter + `anthropic/claude-sonnet-4.6`; doctor, tests, docs, demos, examples |

## Historical ledger (`v0.2.0` ... `f4a676a`)

Commits on the first-parent line from **`v0.2.0`** (`6a06bc9`) through **`f4a676a`** (0.3.0 release line). Reproduce with `git log v0.2.0..f4a676a --reverse`.

| Commit | Summary | Primary themes |
| ------ | ------- | -------------- |
| `8ceda2c` | Harden security, fix bugs, improve docs for 0.2.0 | Security (XSS, safe YAML format), LLM client pooling + retries, MultiStore mirrors, templates, CHANGELOG / CONTRIBUTING |
| `c415ea6` | Critical bugs, resource leak, reliability (code review) | CLI tool events (`name` / `arguments`), YAML scaffold `next`, Runner + httpx lifecycle, snapshot deep copy, `diff --sqlite`, MultiStore.append, tests |
| `cf3879f` | Remove AI-slop patterns from README, DEMO, examples | Documentation tone |
| `2b46cc3` | Animated SVG demos (run / inspect / replay, approval, debug, comparison) | Docs / UX, examples README |
| `b47852b` | Fix clip-path so replay command text is visible | Docs (SVG) |
| `0066209` | Harden runner, SQLite, CLI, persistence | Runner (approvals, snapshots), SQLite WAL + context manager, JSONL Windows locking, MultiStore callbacks, LLM Retry-After, DryRun schema, notebook Mermaid IDs, tests |
| `98b01cb` | Hero demo: refund story + annotations | Docs (SVG) |
| `3b9d371` | Quickstart, scope split, README onboarding, Beta classifier | Docs site map, PyPI Beta, CONTRIBUTING |
| `a93f07a` | GTM-style doc split + INSTALL / CLI / CONFIG / COMPARISON | New doc files, JSONL tail recovery, MultiStore, runner/YAML/CLI/report, cast asset |
| `fb8f94c` | **feat! v0.3.0:** `replayt_examples` rename + doc overhaul | **Breaking** package rename, PRODUCTION / RECIPES, Cursor skills, CLI / types / LLM / tests |
| `59d5f38` | Seal, runner hooks, CI changelog gate, try / ci / report / dry-check | `replayt seal`, `before_step` / `after_step`, `try` / `ci`, dry-check, stakeholder report, workflow meta + LLM experiment, CI gate + tests |
| `7f31743` | Export bundles, report-diff, run metadata, log dir env / subdir | `export-run` tarball + schema, report-diff HTML, `REPLAYT_LOG_DIR`, `--log-subdir`, `--metadata-json`, run-meta filters, state validation, tutorial LangGraph note |
| `f4a676a` | Split Typer app into modules, LLM coercion, CI artifacts | `cli/commands/*`, `llm_coercion`, `ci_artifacts`, `validation`, stores/targets/run_support, approval id string storage, expanded tests + docs |

## Thematic rollup (0.3.0 release line)

1. **Breaking:** Tutorial package **`examples` -> `replayt_examples`** (`fb8f94c`).
2. **CLI surface:** Modular commands (`f4a676a`); validate / dry-check, try, ci, seal, export, report-diff, doctor, init (`59d5f38`, `7f31743`, `f4a676a`).
3. **Runner & workflow:** Hooks, approvals, experiment metadata, YAML graph inference (`59d5f38`, `0066209`, `a93f07a`, `c415ea6`).
4. **Persistence:** SQLite WAL, JSONL locking, MultiStore (`0066209`, `a93f07a`, `c415ea6` and follow-ups in **CHANGELOG** **0.3.0**).
5. **LLM:** Coercion, streaming, size limits, retries (`8ceda2c`, `0066209`, `a93f07a`, `f4a676a`).
6. **CI & docs:** Changelog gate (`59d5f38`); INSTALL / CLI / CONFIG / COMPARISON / demos (`3b9d371`, `a93f07a`, `fb8f94c`, SVG commits).

## How this relates to `CHANGELOG.md`

- **`## 0.4.0`** matches git tag **`v0.4.0`** and the **0.4.0 delta** table above.
- **`## 0.3.0`** is the user-facing rollup for the **historical ledger** through **`f4a676a`**.
- **`## 0.2.0`** matches tag **`v0.2.0`**; **`8ceda2c`** is the first commit after that tag on `main` but documents the same hardening themes as the 0.2.0 notes.
- **`## Unreleased`** is for work **after** **`v0.4.0`** not yet versioned.

Refresh the **Commit ledger (next release)** when you ship again: set a new baseline tag in the title and run `git log <new-tag>..HEAD --reverse`.
