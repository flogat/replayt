# CLI reference

All commands support Typer’s `--help`. Most read/write commands accept `--log-dir`, optional `--log-subdir`, and optional `--sqlite` unless noted; defaults match [`CONFIG.md`](CONFIG.md) when you use project config (and `REPLAYT_LOG_DIR` when the CLI default log root applies).

## `replayt init [--path DIR] [--force] [--ci github]`

Write `workflow.py`, `.env.example`, and a `.gitignore` snippet (`.replayt/`, `.env`, …). Refuses to overwrite unless `--force`. **`--ci github`** also writes `.github/workflows/replayt.yml` (replace `CHANGE_ME_MODULE:wf` with your target).

## `replayt run TARGET`

Run a workflow from a module reference, Python file, or YAML file. Common flags: `--output text|json`, `--log-mode …`, `--resume`, `--tag key=value` (repeatable), `--metadata-json '{…}'` (`run_started.run_metadata`), **`--experiment-json '{…}'`** (`run_started.experiment`, merged into per-call LLM `effective`), `--log-subdir NAME` (one segment under the resolved log root), `--timeout SECONDS`, **`--inputs-json`** or **`--inputs-file PATH`** (mutually exclusive), `--dry-run` (placeholder LLM), `--dry-check` (validate graph + optional JSON blobs; with **`--output json`** prints a `replayt.validate_report.v1` object and exits `1` if not ok), `--strict-graph` (fail validation when there are 2+ states but no declared transitions). Graph validation runs before every real execution (not only `--dry-check`).

**Exit codes:** `0` completed, `1` failed, `2` paused (approval required).

**CI-style artifacts (optional):** set env **`REPLAYT_JUNIT_XML`** to a path to write the same minimal JUnit XML as **`replayt ci --junit-xml`**, and **`REPLAYT_GITHUB_SUMMARY=1`** to append the same markdown summary as **`replayt ci --github-summary`** when **`GITHUB_STEP_SUMMARY`** is set.

## `replayt try`

Same options as `replayt run` except the target is fixed to the packaged hello-world tutorial (`replayt_examples.e01_hello_world:wf`). **Default:** placeholder LLM (`--dry-run`); pass **`--live`** to call the provider (needs `OPENAI_API_KEY`). Use `--customer-name` to set the tutorial input (default `Sam`).

## `replayt ci TARGET`

Same behavior and flags as `replayt run` (including **`--inputs-file`**, **`--metadata-json`**, **`--experiment-json`**), plus **`--strict-graph`**, **`--junit-xml PATH`** (minimal JUnit file for the run outcome), and **`--github-summary`** (append markdown to `GITHUB_STEP_SUMMARY` when that env var is set). Prints a one-line reminder of exit codes for pipelines. See [`RECIPES.md`](RECIPES.md) for GitHub Actions examples.

`TARGET` can be:

- `module:variable` (e.g. `replayt_examples.e01_hello_world:wf`)
- `workflow.py` (must export `wf` or `workflow`)
- `workflow.yaml` / `workflow.yml` (requires `pip install replayt[yaml]`)

## `replayt inspect RUN_ID`

Summary and event list for a run. `--output json` (or legacy `--json`) prints `{"summary": …, "events": …}`.

## `replayt replay RUN_ID`

Recorded execution timeline **without** calling model APIs. `--format html` emits a self-contained page (Tailwind CDN); `--out PATH` writes a file.

## `replayt report RUN_ID`

Self-contained HTML report (summary, states, structured outputs, tool calls, token usage, approvals when present). `--style default|stakeholder` — **stakeholder** hides tool-call and token sections and leads with run + approval context (approval **details** and request/resolve timestamps when present in JSONL). `--out PATH` writes a file; omit `--out` for stdout.

## `replayt report-diff RUN_A RUN_B`

Side-by-side HTML comparison of two runs (workflow, status, state chain, structured outputs, approval counts). `--out PATH` recommended; stdout is valid HTML.

## `replayt export-run RUN_ID --out bundle.tar.gz`

Write a tarball: sanitized `events.jsonl` (`--export-mode redacted|full|structured_only`) plus `manifest.json`. See [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md).

## `replayt bundle-export RUN_ID --out bundle.tar.gz`

Stakeholder-oriented archive: **`report.html`** (default `--report-style stakeholder`), **`timeline.html`** (same as `replayt replay --format html`), sanitized **`events.jsonl`**, and **`manifest.json`** (`schema: replayt.bundle_export.v1`). Optional **`--target`** adds **`workflow.mmd.txt`** (Mermaid source).

## `replayt log-schema`

Print the bundled JSON Schema for one JSONL event line (stdout)—useful for CI or codegen.

## `replayt resume TARGET RUN_ID --approval ID`

Resolve an approval gate and continue a paused run. Same exit codes as `run`. Use `--reject` to reject the approval. Optional **`--reason`**, **`--actor-json '{…}'`**, and **`--resolver NAME`** (default `cli`) are stored on the `approval_resolved` event.

If project config defines **`resume_hook`** (argv list) or env **`REPLAYT_RESUME_HOOK`** is set, that command runs **first** with `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_APPROVAL_ID`, and `REPLAYT_REJECT` (`0` or `1`) in the environment; non-zero exit aborts resume without writing `approval_resolved`. A **default 120s** wall-clock limit applies unless you set **`resume_hook_timeout`** / **`REPLAYT_RESUME_HOOK_TIMEOUT`** (≤ 0 = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt graph TARGET`

Print a Mermaid graph of the workflow to stdout.

## `replayt validate TARGET`

Validate workflow graph without calling an LLM: initial state set and must name a declared `@wf.step`, transition targets exist, no orphan states (when `note_transition` edges are present), handlers present. **`--strict-graph`** additionally requires at least one declared transition when there are two or more states. Optional **`--inputs-json` / `--inputs-file`**, **`--metadata-json`**, **`--experiment-json`** only check JSON parse/serializability (same as `run --dry-check`). **`--format text|json`** — JSON emits `replayt.validate_report.v1` and exits `1` when not ok. Exit `0` if valid, `1` if not. CI-friendly.

## `replayt diff RUN_A RUN_B`

Compare two runs: states visited, structured outputs, tool calls, status, latency. `--output json` for machine-readable output.

## `replayt seal RUN_ID`

Write a JSON manifest next to the run’s JSONL file (default `<log-dir>/<run_id>.seal.json`) with per-line and full-file SHA-256 digests. **Best-effort** audit helper: anyone who can edit the log directory can replace both files—use WORM storage or external signing if you need stronger guarantees. SQLite-only runs are not supported (no primary JSONL path).

## `replayt gc --older-than DURATION`

Delete JSONL run logs older than a duration (`90d`, `24h`, …). `--dry-run` to preview.

## `replayt runs`

List recent local runs. `--tag key=value` (repeatable) to filter. `--run-meta key=value` (repeatable) filters on `run_started.run_metadata` (string equality). **`--experiment key=value`** filters on `run_started.experiment`.

## `replayt stats [--days N] [--tag key=value] [--run-meta key=value] [--experiment key=value] [--output text|json]`

Aggregate counts, average `llm_response` latency, token usage, top failure states, event time range.

## `replayt doctor`

Check install, env vars, optional YAML extra, and default provider connectivity. **`--format json`** prints `replayt.doctor_report.v1` with a **`healthy`** boolean: exit `0` when healthy, `1` otherwise. **`healthy`** ignores missing **`openai_api_key`** and missing project config so CI can validate graphs without secrets; other checks (including **`yaml_extra`** and **`provider_connectivity`** unless `--skip-connectivity`) must pass.
