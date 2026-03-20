# Changelog

## Unreleased

- Documentation: split composition patterns into [`docs/EXAMPLES_PATTERNS.md`](docs/EXAMPLES_PATTERNS.md); add [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/CLI.md`](docs/CLI.md), [`docs/CONFIG.md`](docs/CONFIG.md), [`docs/COMPARISON.md`](docs/COMPARISON.md); README above-the-fold mental model + Beta callout; quickstart sections for failed runs and minimal LLM step; illustrative [`docs/replayt-demo.cast`](docs/replayt-demo.cast); update [`docs/DEMO.md`](docs/DEMO.md) and docs index.

## 0.2.0 — 2026-03-20

- Documentation: add [`docs/QUICKSTART.md`](docs/QUICKSTART.md) and [`docs/SCOPE.md`](docs/SCOPE.md); tighten README above-the-fold (comparison table, `pip install replayt`, `replayt report`, links); trim [`docs/DEMO.md`](docs/DEMO.md) to checklist; fix examples README link to [`docs/STYLE.md`](docs/STYLE.md); PyPI classifier **Beta**.
- HTML-escape all user-facing values in `RunResult._repr_html_` to prevent XSS in notebooks.
- Harden YAML workflow prompt interpolation against attribute-access injection (`format_map` replaced with safe formatter).
- Reuse `httpx.Client` across LLM calls for connection pooling and lower latency.
- Add opt-in HTTP retry via `LLMSettings(http_retries=N)` for transient errors (429, 502, 503, 504) with exponential backoff. Default is `0` (no retries) to stay explicit per design principle #2.
- Fix `DryRunLLMClient._minimal_json_from_schema` dead-code condition that included all fields regardless of `required`.
- Fix `tool-using` init template to match actual `ToolRegistry.register()` API.
- `MultiStore` mirror writes are now best-effort; failures are logged instead of crashing the run.

## 0.1.0 — 2026-03-20

- Initial public skeleton: `Workflow` / `Runner`, JSONL + SQLite persistence, Typer CLI, three examples.
