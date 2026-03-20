# Documentation

## What's here

- [`QUICKSTART.md`](QUICKSTART.md) — five-minute path: install, first run, replay semantics diagram, annotated JSONL sample, failed-run inspect, minimal LLM step.
- [`INSTALL.md`](INSTALL.md) — venv shells, `.env` loading, common install errors.
- [`PRODUCTION.md`](PRODUCTION.md) — finite-run model, logs/PII, approvals, CI, multi-tenant sketch.
- [`RECIPES.md`](RECIPES.md) — LLM client configuration, CI exit codes, mocks pointer.
- [`CLI.md`](CLI.md) — full CLI command reference.
- [`CONFIG.md`](CONFIG.md) — `.replaytrc.toml` and `[tool.replayt]` defaults for the CLI.
- [`COMPARISON.md`](COMPARISON.md) — how replayt relates to plain Python, agent frameworks, Temporal, hosted stacks.
- [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md) — composition recipes (approval bridge, queue worker, tests, …).
- [`SCOPE.md`](SCOPE.md) — long-form scope: features that stay out of core and what to build in your stack instead.
- [`DEMO.md`](DEMO.md) — smoke tests, asciinema cast, release reminder.
- [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md) — JSONL event schema for replayt run logs, logging modes, and the optional SQLite mirror.
- [`STYLE.md`](STYLE.md) — lightweight style guidance for future UI/docs additions.
- [`architecture.mmd`](architecture.mmd) — Mermaid source for the architecture diagram.

## Maintainers

- [`RELEASE_INVENTORY.md`](RELEASE_INVENTORY.md) — commit-level rollup since git tag **`v0.2.0`** (useful when writing release notes).

## Related guides

- [`../README.md`](../README.md) — main project overview, quickstart, examples, and links into the rest of the docs.
- [`../src/replayt_examples/README.md`](../src/replayt_examples/README.md) — linear tutorial (14 runnable workflows).
