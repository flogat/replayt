# Documentation

## Docs

- [`QUICKSTART.md`](QUICKSTART.md): install, first run, replay semantics, an annotated JSONL sample, failed-run inspect, and a minimal LLM step.
- [`INSTALL.md`](INSTALL.md): venv shells, `.env` loading, and common install errors.
- [`PRODUCTION.md`](PRODUCTION.md): finite-run model, logs and PII, approvals, CI, and a multi-tenant sketch.
- [`RECIPES.md`](RECIPES.md): LLM client configuration, CI exit codes, and mock guidance.
- [`CLI.md`](CLI.md): full CLI command reference.
- [`CONFIG.md`](CONFIG.md): `.replaytrc.toml` and `[tool.replayt]` defaults for the CLI.
- [`COMPARISON.md`](COMPARISON.md): how replayt relates to plain Python, agent frameworks, Temporal, and hosted stacks.
- [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md): composition recipes such as approval bridges, queue workers, and tests.
- [`SCOPE.md`](SCOPE.md): long-form scope and what belongs in your stack instead of core.
- [`DEMO.md`](DEMO.md): smoke tests, the asciinema cast, and release reminders.
- [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md): JSONL event schema, logging modes, and the optional SQLite mirror.
- [`STYLE.md`](STYLE.md): lightweight style guidance for future UI and docs additions.
- [`architecture.mmd`](architecture.mmd): Mermaid source for the architecture diagram.

## Maintainer docs

- [`CODE_REVIEW_2026-03-21.md`](CODE_REVIEW_2026-03-21.md): standing standalone review record with findings, mitigations, and verification notes from the current repo pass.
- [`RELEASE_INVENTORY.md`](RELEASE_INVENTORY.md): commit-level rollup since git tag **`v0.2.0`** for release-note work.
- [`ARCHETYPE_FEATURE_BRAINSTORM.md`](ARCHETYPE_FEATURE_BRAINSTORM.md): ten backlog ideas from ten developer archetypes, each marked as in-core or composition.
- [`PUBLIC_API_CONTRACT.json`](PUBLIC_API_CONTRACT.json): checked-in top-level `replayt` API snapshot for semver review via `python scripts/public_api_report.py --check docs/PUBLIC_API_CONTRACT.json`.

## Related guides

- [`../README.md`](../README.md): main project overview, quickstart, examples, and links into the rest of the docs.
- [`../src/replayt_examples/README.md`](../src/replayt_examples/README.md): linear tutorial with 14 runnable workflows.
