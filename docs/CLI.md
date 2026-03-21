# CLI reference

All commands support Typer's `--help`. Most read/write commands accept `--log-dir`, optional `--log-subdir`, and optional `--sqlite` unless noted; defaults match [`CONFIG.md`](CONFIG.md) when you use project config (and `REPLAYT_LOG_DIR` when the CLI default log root applies).

## `replayt init [--path DIR] [--force] [--ci github]`

Write `workflow.py` or `workflow.yaml`, `inputs.example.json`, `.env.example`, and a `.gitignore` snippet (`.replayt/`, `.env`, ...). Refuses to overwrite unless `--force`. **`--template`** supports `basic`, `approval`, `tool-using`, `yaml`, `issue-triage`, and `publishing-preflight`. **`--ci github`** also writes `.github/workflows/replayt.yml` (replace `CHANGE_ME_MODULE:wf` with your target).

## `replayt run [TARGET]`

Run a workflow from a module reference, Python file, or YAML file. **`TARGET` is optional** when env **`REPLAYT_TARGET`** is set or project config defines **`target`** (see [`CONFIG.md`](CONFIG.md)); an explicit **`TARGET` argument always wins**. Common flags: `--output text|json`, `--log-mode ...`, `--redact-key FIELD` (repeatable, scrubs matching structured keys from logged payloads), `--resume`, `--tag key=value` (repeatable), `--metadata-json '{...}'` (`run_started.run_metadata`), **`--experiment-json '{...}'`** (`run_started.experiment`, merged into per-call LLM `effective`), `--log-subdir NAME` (one segment under the resolved log root), `--timeout SECONDS`, **`--inputs-json`** or **`--inputs-file PATH`** (mutually exclusive; `--inputs-json @path.json` is a shortcut for reading a file), `--dry-run` (placeholder LLM), `--dry-check` (validate graph + optional JSON blobs; with **`--output json`** prints a `replayt.validate_report.v1` object and exits `1` if not ok), `--strict-graph` (fail validation when there are 2+ states but no declared transitions). Graph validation runs before every real execution (not only `--dry-check`). `run_started` now also records a safe `runtime` snapshot (engine/store class plus non-secret LLM settings such as base URL and model).

If project config defines **`run_hook`** (argv list) or env **`REPLAYT_RUN_HOOK`** is set, that command runs before execution with `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_RUN_MODE` (`run` or `resume`), `REPLAYT_LOG_DIR`, `REPLAYT_LOG_MODE`, `REPLAYT_DRY_RUN`, and optional `REPLAYT_SQLITE` in the environment; non-zero exit aborts before replayt writes new events. A default 120s wall-clock limit applies unless you set **`run_hook_timeout`** / **`REPLAYT_RUN_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

**Exit codes:** `0` completed, `1` failed, `2` paused (approval required).

Listing, inspection, export, and seal helpers use **`1`** for missing runs, invalid arguments, or verification failures so **`2`** stays reserved for approval pauses on **`replayt run`** / **`replayt ci`**.

**CI-style artifacts (optional):** set env **`REPLAYT_JUNIT_XML`** to a path to write the same minimal JUnit XML as **`replayt ci --junit-xml`**, **`REPLAYT_SUMMARY_JSON`** to write the same machine-readable JSON artifact as **`replayt ci --summary-json`**, and **`REPLAYT_GITHUB_SUMMARY=1`** to append the same markdown summary as **`replayt ci --github-summary`** when **`GITHUB_STEP_SUMMARY`** is set. When a summary path is in effect (flag or **`REPLAYT_SUMMARY_JSON`**), optional env **`REPLAYT_CI_METADATA_JSON`** may hold a JSON **object** of pipeline fields (build id, commit, job URL); valid values are merged into the summary payload as **`ci_metadata`** (invalid JSON or a non-object fails fast before the run starts). See [`CONFIG.md`](CONFIG.md) and [`RECIPES.md`](RECIPES.md).

## `replayt try`

Run one of the packaged tutorial workflows without creating a local file first. Use **`--list`** to see the curated examples, **`--example KEY`** to pick one, and optional **`--inputs-json`** / **`--inputs-file`** to override the sample payload. **Default:** placeholder LLM (`--dry-run`); pass **`--live`** to call the provider (needs `OPENAI_API_KEY`). `--customer-name` still customizes the default `hello-world` payload.

**Materialize locally:** **`--copy-to DIR`** copies the example module as **`workflow.py`** plus **`inputs.example.json`** from the catalog (no run). Refuses to overwrite unless **`--force`**. **`--output json`** prints **`replayt.try_copy.v1`** with absolute paths. Cannot be combined with **`--list`**, **`--live`**, **`--dry-check`**, **`--inputs-json`**, **`--inputs-file`**, **`--run-id`**, or **`--timeout`**.

## `replayt ci [TARGET]`

Same behavior and flags as `replayt run` (including optional **`TARGET`** resolution via **`REPLAYT_TARGET`** / project **`target`**, **`--inputs-file`**, **`--metadata-json`**, **`--experiment-json`**), plus **`--strict-graph`**, **`--junit-xml PATH`** (minimal JUnit file for the run outcome), **`--summary-json PATH`** (machine-readable `replayt.ci_run_summary.v1`: workflow, `run_id`, status, final state, error, **`exit_code`** matching the CLI, **`target`**, resolved **`log_dir`**, optional **`sqlite`**, **`dry_run`**, wall-clock **`duration_ms`**, and optional **`ci_metadata`** when **`REPLAYT_CI_METADATA_JSON`** is set), and **`--github-summary`** (append markdown to `GITHUB_STEP_SUMMARY` when that env var is set). Prints a one-line reminder of exit codes for pipelines. See [`RECIPES.md`](RECIPES.md) for GitHub Actions examples.

`TARGET` can be:

- `module:variable` (e.g. `replayt_examples.e01_hello_world:wf`)
- `workflow.py` (must export `wf` / `workflow`, or exactly one top-level `Workflow` object)
- `workflow.yaml` / `workflow.yml` (requires `pip install replayt[yaml]`)

If `module:variable` fails with an import error, replayt prints hints: install your project editable (`pip install -e .`), add your source tree to `PYTHONPATH` when you use a `src/` layout without packaging, pass a `workflow.py` / YAML path instead, or run `replayt doctor --target TARGET` once imports succeed. When the module loads but a dependency import fails, the error names the missing module.

## `replayt inspect RUN_ID`

Summary and event list for a run. `--output json` (or legacy `--json`) prints `{"summary": ..., "events": ...}`. Repeat **`--event-type TYPE`** to restrict the printed / JSON `events` array to matching JSONL `type` values (OR semantics); **`summary`** still describes the full run. When filtering is active, JSON also includes **`event_type_filter`**.

If there is no JSONL timeline for that id, replayt exits **1** (lookup / user error; not the same as exit **2** for paused runs) and prints a hint to run **`replayt runs --limit 10`**, repeating **`--log-dir`**, **`--log-subdir`**, and **`--sqlite`** only when you passed them on the failing command so the listing hits the same store. The same hint appears for **`replay`**, **`report`**, **`report-diff`**, **`export-run`**, and **`bundle-export`** when the id is missing or empty.

## `replayt replay RUN_ID`

Recorded execution timeline **without** calling model APIs. `--format html` emits a self-contained page (Tailwind CDN); `--out PATH` writes a file.

## `replayt report RUN_ID`

Self-contained HTML report (summary, states, structured outputs, tool calls, token usage, approvals when present), or Markdown via **`--format markdown`** for pasting into tickets, chat, or email (same `--style` rules: **stakeholder** / **support** still omit tool-call and token sections). `--style default|stakeholder|support` - **stakeholder** hides tool-call and token sections and leads with run + approval context, while **support** also leads with failure, retry, and parse-failure context for PM/support handoffs. Paused runs in Markdown include a copy-paste **`replayt resume TARGET …`** hint (replace `TARGET` with your workflow). Approval cards now surface resolver / reason / actor fields from `approval_resolved` plus the applied resume path when present in JSONL. `--out PATH` writes a file; omit `--out` for stdout.

## `replayt report-diff RUN_A RUN_B`

Side-by-side HTML comparison of two runs (workflow, status, state chain, run metadata / experiment / workflow metadata, failure signals, structured outputs, approvals). `--out PATH` recommended; stdout is valid HTML.

## `replayt export-run RUN_ID --out bundle.tar.gz`

Write a tarball: sanitized `events.jsonl` (`--export-mode redacted|full|structured_only`) plus `manifest.json`. Pass **`--seal`** to also include `events.seal.json`, a SHA-256 manifest for the exported `events.jsonl`. See [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md).

If project config defines **`export_hook`** or env **`REPLAYT_EXPORT_HOOK`** is set, that command runs after the run's events are loaded but **before** the tarball is written, with `REPLAYT_RUN_ID`, `REPLAYT_EXPORT_KIND` (`export_run` or `bundle_export`), `REPLAYT_LOG_DIR`, `REPLAYT_EXPORT_MODE`, `REPLAYT_EXPORT_OUT` (intended archive path), `REPLAYT_EXPORT_SEAL` (`0` or `1`), `REPLAYT_EXPORT_EVENT_COUNT`, optional `REPLAYT_SQLITE`, and `REPLAYT_BUNDLE_REPORT_STYLE` (**bundle-export** only) in the environment; non-zero exit aborts the export. Default **120s** wall-clock limit unless **`export_hook_timeout`** / **`REPLAYT_EXPORT_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt bundle-export RUN_ID --out bundle.tar.gz`

Stakeholder-oriented archive: **`report.html`** (default `--report-style stakeholder`; also accepts `support`), **`timeline.html`** (same as `replayt replay --format html`), sanitized **`events.jsonl`**, and **`manifest.json`** (`schema: replayt.bundle_export.v1`). Pass **`--seal`** to also include `events.seal.json` for the exported JSONL. Optional **`--target`** adds **`workflow.mmd.txt`** (Mermaid source). The optional **`export_hook`** / **`REPLAYT_EXPORT_HOOK`** gate applies the same way as for **`export-run`** (see above).

## `replayt log-schema`

Print the bundled JSON Schema for one JSONL event line (stdout) - useful for CI or codegen.

## `replayt resume TARGET RUN_ID --approval ID`

Resolve an approval gate and continue a paused run. Same exit codes as `run`. Use `--reject` to reject the approval. Optional **`--reason`**, **`--actor-json '{...}'`**, and **`--resolver NAME`** (default `cli`) are stored on the `approval_resolved` event. Use **`--require-actor-key FIELD`** (repeatable) or project config `approval_actor_required_keys = [...]` when resume decisions must include fixed audit fields such as `email` or `ticket_id`.

If project config defines **`resume_hook`** (argv list) or env **`REPLAYT_RESUME_HOOK`** is set, that command runs **first** with `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_APPROVAL_ID`, and `REPLAYT_REJECT` (`0` or `1`) in the environment; non-zero exit aborts resume without writing `approval_resolved`. A **default 120s** wall-clock limit applies unless you set **`resume_hook_timeout`** / **`REPLAYT_RESUME_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt graph TARGET`

Print a Mermaid graph of the workflow to stdout.

## `replayt contract TARGET`

Print a snapshot-friendly workflow contract. `--format json` emits `replayt.workflow_contract.v1` with workflow metadata, declared edges, retry policies, and per-step `expects` keys/types so CI or review tooling can diff the public workflow surface without executing it.

## `replayt validate TARGET`

Validate workflow graph without calling an LLM: initial state set and must name a declared `@wf.step`, transition targets exist, no orphan states (when `note_transition` edges are present), handlers present. **`--strict-graph`** also requires at least one declared transition when there are two or more states. Optional **`--inputs-json` / `--inputs-file`**, **`--metadata-json`**, **`--experiment-json`** only check JSON parse/serializability (same as `run --dry-check`). **`--format text|json`** - JSON emits `replayt.validate_report.v1` and exits `1` when not ok. Exit `0` if valid, `1` if not. CI-friendly.

## `replayt diff RUN_A RUN_B`

Compare two runs: states visited, structured outputs, tool calls, status, latency. `--output json` for machine-readable output.

## `replayt seal RUN_ID`

Write a JSON manifest next to the run's JSONL file (default `<log-dir>/<run_id>.seal.json`) with per-line and full-file SHA-256 digests. **Best-effort** audit helper: anyone who can edit the log directory can replace both files - use WORM storage or external signing if you need stronger guarantees. SQLite-only runs are not supported (no primary JSONL path).

If project config defines **`seal_hook`** or env **`REPLAYT_SEAL_HOOK`** is set, that command runs after the JSONL is read and digests are computed but **before** the manifest is written, with `REPLAYT_RUN_ID`, `REPLAYT_LOG_DIR`, `REPLAYT_SEAL_JSONL`, `REPLAYT_SEAL_OUT`, and `REPLAYT_SEAL_LINE_COUNT` in the environment; non-zero exit aborts without creating the manifest. Default **120s** wall-clock limit unless **`seal_hook_timeout`** / **`REPLAYT_SEAL_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md). Tarball **`export-run`** / **`bundle-export`** gates still use **`export_hook`** only.

## `replayt verify-seal RUN_ID`

Re-hash the JSONL and compare it to an existing manifest from **`replayt seal`** or from **`export-run` / `bundle-export --seal`** (`replayt.export_seal.v1`). Default manifest path is `<log-dir>/<run_id>.seal.json`. Use **`--manifest`** / **`--jsonl`** when you extracted **`events.seal.json`** and **`events.jsonl`** from a tarball (the export manifest records a relative **`jsonl_path`**). **`--output json`** prints **`replayt.verify_seal_report.v1`**. Exit **`0`** when digests match, **`1`** on mismatch, **`2`** on missing files or invalid manifest.

## `replayt gc --older-than DURATION`

Delete JSONL run logs older than a duration (`90d`, `24h`, ...). `--dry-run` to preview.

## `replayt runs`

List recent local runs. **`--status completed|failed|paused|unknown`** (repeatable; OR semantics) filters on the best-effort terminal status derived from JSONL the same way as the listing columns (`unknown` when the log has no `run_completed` / `run_paused` yet). `--tag key=value` (repeatable) to filter. `--run-meta key=value` (repeatable) filters on `run_started.run_metadata` (string equality). **`--experiment key=value`** filters on `run_started.experiment`. **`--tool NAME`** (repeatable; OR) keeps runs that recorded at least one JSONL **`tool_call`** whose payload **`name`** equals **`NAME`** (exact string match).

## `replayt stats [--days N] [--tag key=value] [--run-meta key=value] [--experiment key=value] [--tool NAME] [--output text|json]`

Aggregate counts, average `llm_response` latency, token usage, top failure states, event time range. **`--tool`** uses the same **`tool_call`** **`name`** filter as **`replayt runs`**.

## `replayt doctor`

Check install, env vars, optional YAML extra, default provider connectivity, and best-effort filesystem readiness for the resolved `log_dir` / optional SQLite mirror path. `doctor` also reports soft trust-boundary warnings for risky defaults such as remote plain-HTTP base URLs, embedded credentials in `OPENAI_BASE_URL`, `log_mode=full`, or (on POSIX) a **`log_dir`** that is world-readable or world-writable. JSON output includes **`credential_env`**: a fixed list of common third-party LLM credential variable names each with boolean **`present`** (never values), plus a soft **`credential_env_extra_providers`** check when non-`OPENAI_API_KEY` entries from that list are non-empty in the process environment (replayt's default client does not read them). Optional **`--target TARGET`** plus **`--strict-graph`** / **`--inputs-json`** / **`--inputs-file`** preflight-loads a workflow and runs the same graph/input validation as `replayt validate` without executing it. **`--format json`** prints `replayt.doctor_report.v1` with a **`healthy`** boolean: exit `0` when healthy, `1` otherwise. **`healthy`** ignores missing **`openai_api_key`**, missing project config, and these soft trust warnings so CI can validate graphs without secrets; other checks (including **`yaml_extra`**, **`provider_connectivity`** unless `--skip-connectivity`, path-readiness failures, and optional `target_validation`) must pass.

## `replayt config`

Print the effective CLI defaults after CLI flags, project config, and environment variables are resolved. `--format json` emits `replayt.config_report.v1` with the resolved log paths, mirror policy, run/resume policy-hook settings, redaction keys, approval-actor requirements, **`project_config.unknown_keys`** for typo detection (unsupported keys are ignored; see [`CONFIG.md`](CONFIG.md#unknown-keys)), trust-boundary warnings (including POSIX **`log_dir`** permission hints when applicable), filesystem-readiness checks for the effective log / SQLite destinations, the active provider/base URL/model plus source labels such as `project_config:model` or `env:OPENAI_BASE_URL`, and **`llm.credential_env`** (same presence-only name list as **`replayt doctor`** JSON). Text output may print a **`credential_env_note`** when extra vendor credential env vars are set but not consumed by replayt's OpenAI-compat client.

## `replayt version`

Print the installed **replayt** package version, Python runtime, and OS platform. **`--format json`** emits **`replayt.version_report.v1`** with structured Python version fields plus a map of **stable `schema` ids** used by other JSON CLI outputs (`contract`, `validate`, `doctor`, `config`, `ci` summary) so CI matrices and wrappers can probe compatibility without scraping human text. Exit **0** always.
