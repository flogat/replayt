# Changelog

## Unreleased

- **Runner / workflow / YAML:** `replayt seal` (SHA-256 manifest for JSONL run logs); optional `Runner(..., before_step=..., after_step=...)` hooks; optional `Workflow(..., llm_defaults=...)` and `meta["llm_defaults"]` (merged into `LLMBridge` defaults; omitted from logged `workflow_meta`); YAML infers `note_transition` edges from `next` / `branch` / `approval` so graph validation matches Python workflows. PR CI gate requiring `CHANGELOG.md` when protected paths change; test that tutorial `MODULE:wf` targets from the examples README stay importable.
- **CLI:** `replayt validate` (`--format json` → `replayt.validate_report.v1`) and `replayt run --dry-check` (`--output json`, same schema); **`--inputs-file`** for `run` / `ci` / `validate` (mutually exclusive with `--inputs-json`; UTF-8 with clear errors). **`--strict-graph`** on `validate` / `run` / `ci`. **`--experiment-json`** → `run_started.experiment` and LLM `effective`; **`replayt runs`** / **`stats`** filter **`--experiment key=value`**. **`replayt resume`:** `--reason`, `--actor-json`, `--resolver`, optional **`resume_hook`** / **`REPLAYT_RESUME_HOOK`**. **`replayt doctor --format json`** (`replayt.doctor_report.v1`, **`healthy`** + exit). **`replayt bundle-export`**; **`replayt init --ci github`**. **`replayt ci`:** `--junit-xml`, `--github-summary` (paths forwarded without mutating process env; **`REPLAYT_JUNIT_XML`** still works for `replayt run`). **`replayt try`** defaults offline (`--live` for real LLM). Richer stakeholder **`replayt report`** (approval details + timestamps). `replayt.cli.validation` / `replayt.cli.ci_artifacts` module split; `build_run_report_html` in `report_template`.
- Docs: README + tutorial README expand **composition** (streaming / planner / agent-framework boundaries).

## 0.3.0 — 2026-03-20

- **Breaking:** the tutorial package on PyPI is now **`replayt_examples`** (was `examples`). Update targets: `replayt run replayt_examples.e01_hello_world:wf` (not `examples.*`).
- Documentation: add [`docs/PRODUCTION.md`](docs/PRODUCTION.md) and [`docs/RECIPES.md`](docs/RECIPES.md); README slimming (recipes extracted, merged “when to use” + positioning, embedded architecture Mermaid, PII/log note, asciinema share hint); quickstart “replay vs regenerate” diagram + PII note; tutorial README PyPI-first install and early CI/mock pointer; docs index updates.

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
