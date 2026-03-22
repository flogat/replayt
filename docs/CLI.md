# CLI reference

All commands support Typer's `--help`. Most read/write commands accept `--log-dir`, optional `--log-subdir`, and optional `--sqlite` unless noted; defaults match [`CONFIG.md`](CONFIG.md) when you use project config (and `REPLAYT_LOG_DIR` when the CLI default log root applies).

When the **`replayt`** entry point is not on your **`PATH`** (minimal containers, some **`pip install --user`** shells), run the same CLI as **`python -m replayt`** with the same subcommands and flags, for example **`python -m replayt version --format json`**.

## `replayt init [--path DIR] [--force] [--ci github]`

Write `workflow.py` or `workflow.yaml`, `inputs.example.json`, `.env.example`, and a `.gitignore` snippet (`.replayt/`, `.env`, ...). Refuses to overwrite unless `--force`. **`--template`** supports `basic`, `approval`, `tool-using`, `yaml`, `issue-triage`, and `publishing-preflight`. **`--ci github`** also writes `.github/workflows/replayt.yml` (replace `CHANGE_ME_MODULE:wf` with your target). The command now prints copy-paste next steps with shell-specific venv activation lines, **`replayt doctor --skip-connectivity --target ...`**, and **`--inputs-file`** examples; LLM-backed templates start with a suggested **`--dry-run`** before the live run.

## `replayt run [TARGET]`

Run a workflow from a module reference, Python file, or YAML file. **`TARGET` is optional** when env **`REPLAYT_TARGET`** is set or project config defines **`target`** (see [`CONFIG.md`](CONFIG.md)); an explicit **`TARGET` argument always wins**. Common flags: `--output text|json`, `--log-mode ...`, `--redact-key FIELD` (repeatable, scrubs matching structured keys from logged payloads), `--resume`, `--tag key=value` (repeatable), `--metadata-json '{...}'` (`run_started.run_metadata`), **`--experiment-json '{...}'`** (`run_started.experiment`, merged into per-call LLM `effective`), `--log-subdir NAME` (one segment under the resolved log root), `--timeout SECONDS`, **`--inputs-json`** or **`--inputs-file PATH`** (mutually exclusive; `--inputs-json @path.json` is a shortcut for reading a file; when both are omitted, defaults may come from env **`REPLAYT_INPUTS_FILE`** or project **`inputs_file`** (see [`CONFIG.md`](CONFIG.md))), repeatable **`--input key=value`** overrides for the common case where a whole JSON blob is overkill, `--dry-run` (placeholder LLM), `--dry-check` (validate graph + optional JSON blobs; with **`--output json`** prints a `replayt.validate_report.v1` object and exits `1` if not ok), `--strict-graph` (fail validation when there are 2+ states but no declared transitions). Graph validation runs before every real execution (not only `--dry-check`). `run_started` now also records a safe `runtime` snapshot (engine/store class plus non-secret LLM settings such as base URL and model). **`--output json`** emits **`replayt.run_result.v1`**.

**`--input` details:** each flag is `key=value`. Dotted keys build nested objects (`--input issue.title=Crash --input issue.body="Stacktrace..."`). Values are parsed as JSON when possible, so `2`, `false`, `null`, `["a"]`, and `{"k":"v"}` become structured values; anything else stays a string. You can combine **`--input`** with **`--inputs-json`** or **`--inputs-file`**; later `--input` paths override the same keys from the base object.

If project config defines **`run_hook`** (argv list) or env **`REPLAYT_RUN_HOOK`** is set, that command runs before execution with `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_RUN_MODE` (`run` or `resume`), `REPLAYT_LOG_DIR`, `REPLAYT_LOG_MODE`, `REPLAYT_DRY_RUN`, optional `REPLAYT_SQLITE`, and normalized JSON object strings in `REPLAYT_RUN_INPUTS_JSON`, `REPLAYT_RUN_TAGS_JSON`, `REPLAYT_RUN_METADATA_JSON`, and `REPLAYT_RUN_EXPERIMENT_JSON` when those values are present on the CLI. That gives policy wrappers one explicit place to check change tickets, deployment tiers, or tag-based allowlists before replayt writes new events. Successful runs record a compact breadcrumb under **`run_started.runtime.policy_hooks.run`** (`source`, `argv0`, `arg_count`) so the log shows that trusted external code was part of the gate. Non-zero exit aborts before replayt writes new events. A default 120s wall-clock limit applies unless you set **`run_hook_timeout`** / **`REPLAYT_RUN_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

**Exit codes:** `0` completed, `1` failed, `2` paused (approval required).

Listing, inspection, export, and seal helpers use **`1`** for missing runs, invalid arguments, or verification failures so **`2`** stays reserved for approval pauses on **`replayt run`** / **`replayt ci`**.

**CI-style artifacts (optional):** set env **`REPLAYT_JUNIT_XML`** to a path to write the same minimal JUnit XML as **`replayt ci --junit-xml`**, **`REPLAYT_SUMMARY_JSON`** to write the same machine-readable JSON artifact as **`replayt ci --summary-json`**, and **`REPLAYT_GITHUB_SUMMARY=1`** to append the same markdown summary as **`replayt ci --github-summary`** when **`GITHUB_STEP_SUMMARY`** (GitHub Actions) or **`REPLAYT_STEP_SUMMARY`** (any CI: explicit path to append) is set; when both are set, **`GITHUB_STEP_SUMMARY`** wins. When a summary path is in effect (flag or **`REPLAYT_SUMMARY_JSON`**), optional env **`REPLAYT_CI_METADATA_JSON`** may hold a JSON **object** of pipeline fields (build id, commit, job URL); valid values are merged into the summary payload as **`ci_metadata`** (invalid JSON or a non-object fails fast before the run starts). **`replayt config --format json`** and **`replayt doctor --format json`** preview those env-driven artifact sinks so CI can catch missing parents or a missing **`GITHUB_STEP_SUMMARY`** export before the real run. See [`CONFIG.md`](CONFIG.md) and [`RECIPES.md`](RECIPES.md).

## `replayt try`

Run one of the packaged tutorial workflows without creating a local file first. Use **`--list`** to see the curated examples, **`--example KEY`** to pick one, and optional **`--inputs-json`** / **`--inputs-file`** / repeatable **`--input key=value`** to override the sample payload. **Default:** placeholder LLM (`--dry-run`); pass **`--live`** to call the provider (needs `OPENAI_API_KEY`). `--customer-name` still customizes the default `hello-world` payload, and **`--input`** layers on top of that default example object rather than replacing it wholesale.

**Materialize locally:** **`--copy-to DIR`** copies the example module as **`workflow.py`** plus **`inputs.example.json`** from the catalog (no run). Refuses to overwrite unless **`--force`**. **`--output json`** prints **`replayt.try_copy.v1`** with absolute paths. Text output now includes copy-paste follow-up commands (`doctor --skip-connectivity --target`, `run --dry-check --inputs-file`, and **`--dry-run`** first when the example is LLM-backed). Cannot be combined with **`--list`**, **`--live`**, **`--dry-check`**, **`--inputs-json`**, **`--inputs-file`**, **`--input`**, **`--run-id`**, or **`--timeout`**.

## `replayt ci [TARGET]`

Same behavior and flags as `replayt run` (including optional **`TARGET`** resolution via **`REPLAYT_TARGET`** / project **`target`**, **`--inputs-file`**, env/project default inputs, repeatable **`--input`**, **`--metadata-json`**, **`--experiment-json`**), plus **`--strict-graph`**, **`--junit-xml PATH`** (minimal JUnit file for the run outcome), **`--summary-json PATH`** (machine-readable `replayt.ci_run_summary.v1`: workflow, `run_id`, status, final state, error, **`exit_code`** matching the CLI, **`target`**, resolved **`log_dir`**, optional **`sqlite`**, **`dry_run`**, wall-clock **`duration_ms`**, and optional **`ci_metadata`** when **`REPLAYT_CI_METADATA_JSON`** is set), and **`--github-summary`** (append markdown to **`GITHUB_STEP_SUMMARY`** or **`REPLAYT_STEP_SUMMARY`** when set; GitHub wins if both are set). Prints a one-line reminder of exit codes for pipelines. See [`RECIPES.md`](RECIPES.md) for GitHub Actions examples.

`TARGET` can be:

- `module:variable` (e.g. `replayt_examples.e01_hello_world:wf`)
- `workflow.py` (must export `wf` / `workflow`, or exactly one top-level `Workflow` object)
- `workflow.yaml` / `workflow.yml` (requires `pip install replayt[yaml]`)

If `module:variable` fails with an import error, replayt prints hints: install your project editable (`pip install -e .`), add your source tree to `PYTHONPATH` when you use a `src/` layout without packaging, pass a `workflow.py` / YAML path instead, or run `replayt doctor --target TARGET` once imports succeed. When the module loads but a dependency import fails, the error names the missing module.

## `replayt inspect RUN_ID`

Summary and event list for a run. `--output json` (or legacy `--json`) emits **`replayt.inspect_report.v1`** with **`run_id`**, **`summary`**, and **`events`**. Repeat **`--event-type TYPE`** to restrict the printed / JSON `events` array to matching JSONL `type` values (OR semantics); **`summary`** still describes the full run. Repeat **`--note-kind KIND`** to restrict the event list to matching **`step_note`** payload **`kind`** values (exact match; OR semantics). Without **`--event-type`**, **`--note-kind`** shows only matching notes. When filtering is active, JSON also includes **`event_type_filter`** and/or **`note_kind_filter`**.

If there is no JSONL timeline for that id, replayt exits **1** (lookup / user error; not the same as exit **2** for paused runs) and prints a hint to run **`replayt runs --limit 10`**, repeating **`--log-dir`**, **`--log-subdir`**, and **`--sqlite`** only when you passed them on the failing command so the listing hits the same store. The same hint appears for **`replay`**, **`report`**, **`report-diff`**, **`export-run`**, and **`bundle-export`** when the id is missing or empty.

## `replayt replay RUN_ID`

Recorded execution timeline **without** calling model APIs. `--format html` emits a self-contained page (Tailwind CDN); `--out PATH` writes a file.

## `replayt report RUN_ID`

Self-contained HTML report (summary, states, structured outputs, tool calls, token usage, approvals when present), or Markdown via **`--format markdown`** for pasting into tickets, chat, or email (same `--style` rules: **stakeholder** / **support** still omit tool-call and token sections). `--style default|stakeholder|support` - **stakeholder** hides tool-call and token sections and leads with run + approval context, while **support** also leads with failure, retry, and parse-failure context for PM/support handoffs. Paused runs in Markdown include a copy-paste **`replayt resume TARGET …`** hint (replace `TARGET` with your workflow). Approval cards now surface resolver / reason / actor fields from `approval_resolved` plus the applied resume path when present in JSONL. `--out PATH` writes a file; omit `--out` for stdout.

## `replayt report-diff RUN_A RUN_B`

Side-by-side comparison of two runs (workflow, status, state chain, run metadata / experiment / workflow metadata, failure signals, structured outputs, approvals). Default **`--format html`** is a self-contained page; **`--format markdown`** mirrors the same sections for tickets, chat, and docs (no model calls). `--out PATH` writes either format; omit `--out` for stdout.

## `replayt export-run RUN_ID --out bundle.tar.gz`

Write a tarball: sanitized `events.jsonl` (`--export-mode redacted|full|structured_only`) plus `manifest.json`. Pass **`--seal`** to also include `events.seal.json`, a SHA-256 manifest for the exported `events.jsonl`. See [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md).

If project config defines **`export_hook`** or env **`REPLAYT_EXPORT_HOOK`** is set, that command runs after the run's events are loaded but **before** the tarball is written, with `REPLAYT_RUN_ID`, `REPLAYT_EXPORT_KIND` (`export_run` or `bundle_export`), `REPLAYT_LOG_DIR`, `REPLAYT_EXPORT_MODE`, `REPLAYT_EXPORT_OUT` (intended archive path), `REPLAYT_EXPORT_SEAL` (`0` or `1`), `REPLAYT_EXPORT_EVENT_COUNT`, optional `REPLAYT_SQLITE`, and `REPLAYT_BUNDLE_REPORT_STYLE` (**bundle-export** only) in the environment; non-zero exit aborts the export. Successful exports record a compact **`policy_hook`** object in `manifest.json` (`source`, `argv0`, `arg_count`). Default **120s** wall-clock limit unless **`export_hook_timeout`** / **`REPLAYT_EXPORT_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt bundle-export RUN_ID --out bundle.tar.gz`

Stakeholder-oriented archive: **`report.html`** (default `--report-style stakeholder`; also accepts `support`), **`timeline.html`** (same as `replayt replay --format html`), sanitized **`events.jsonl`**, and **`manifest.json`** (`schema: replayt.bundle_export.v1`). Pass **`--seal`** to also include `events.seal.json` for the exported JSONL. Optional **`--target`** adds **`workflow.mmd.txt`** (Mermaid source). The optional **`export_hook`** / **`REPLAYT_EXPORT_HOOK`** gate applies the same way as for **`export-run`** (see above).

## `replayt log-schema`

Print the bundled JSON Schema for one JSONL event line (stdout) - useful for CI or codegen.

## `replayt resume TARGET RUN_ID --approval ID`

Resolve an approval gate and continue a paused run. Same exit codes as `run`. Use `--reject` to reject the approval. Optional **`--reason`**, **`--actor-json '{...}'`**, and **`--resolver NAME`** (default `cli`) are stored on the `approval_resolved` event. Use **`--require-actor-key FIELD`** (repeatable) or project config `approval_actor_required_keys = [...]` when resume decisions must include fixed audit fields such as `email` or `ticket_id`. Use **`--require-reason`** or project config **`approval_reason_required = true`** when every approval or rejection needs a non-empty written justification.

If project config defines **`resume_hook`** (argv list) or env **`REPLAYT_RESUME_HOOK`** is set, that command runs **first** with `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_APPROVAL_ID`, and `REPLAYT_REJECT` (`0` or `1`) in the environment; non-zero exit aborts resume without writing `approval_resolved`. Successful resumes record a compact **`approval_resolved.policy_hook`** object (`source`, `argv0`, `arg_count`) so the run log keeps that external approval gate explicit. A **default 120s** wall-clock limit applies unless you set **`resume_hook_timeout`** / **`REPLAYT_RESUME_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt graph TARGET`

Print a Mermaid graph of the workflow to stdout.

## `replayt contract TARGET`

Print a snapshot-friendly workflow contract. `--format json` emits `replayt.workflow_contract.v1` with workflow metadata, declared edges, retry policies, and per-step `expects` keys/types so CI or review tooling can diff the public workflow surface without executing it. Use **`--snapshot-out PATH`** to write that JSON contract to a checked-in file. Use **`--check PATH`** to compare the current workflow against a previously saved `replayt.workflow_contract.v1` snapshot; text mode prints a unified diff on drift, and JSON mode emits **`replayt.workflow_contract_check.v1`** with **`ok`**, **`snapshot_path`**, and diff lines. Exit **`0`** when the snapshot matches and **`1`** when it drifts or the snapshot file is invalid.

## `replayt validate TARGET`

Validate workflow graph without calling an LLM: initial state set and must name a declared `@wf.step`, transition targets exist, no orphan states (when `note_transition` edges are present), handlers present. **`--strict-graph`** also requires at least one declared transition when there are two or more states. Optional **`--inputs-json` / `--inputs-file`** (or env **`REPLAYT_INPUTS_FILE`** / project **`inputs_file`** when both flags are omitted), repeatable **`--input key=value`**, **`--metadata-json`**, **`--experiment-json`** only check JSON parse/serializability (same as `run --dry-check`). **`--format text|json`** - JSON emits `replayt.validate_report.v1` and exits `1` when not ok. Exit `0` if valid, `1` if not. CI-friendly.

## `replayt diff RUN_A RUN_B`

Compare two runs: states visited, structured outputs, tool calls, status, latency. `--output json` emits **`replayt.diff_report.v1`**.

## `replayt seal RUN_ID`

Write a JSON manifest next to the run's JSONL file (default `<log-dir>/<run_id>.seal.json`) with per-line and full-file SHA-256 digests. **Best-effort** audit helper: anyone who can edit the log directory can replace both files - use WORM storage or external signing if you need stronger guarantees. SQLite-only runs are not supported (no primary JSONL path).

If project config defines **`seal_hook`** or env **`REPLAYT_SEAL_HOOK`** is set, that command runs after the JSONL is read and digests are computed but **before** the manifest is written, with `REPLAYT_RUN_ID`, `REPLAYT_LOG_DIR`, `REPLAYT_SEAL_JSONL`, `REPLAYT_SEAL_OUT`, and `REPLAYT_SEAL_LINE_COUNT` in the environment; non-zero exit aborts without creating the manifest. Successful seals record a compact **`policy_hook`** object in the seal JSON (`source`, `argv0`, `arg_count`). Default **120s** wall-clock limit unless **`seal_hook_timeout`** / **`REPLAYT_SEAL_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md). Tarball **`export-run`** / **`bundle-export`** gates still use **`export_hook`** only.

## `replayt verify-seal RUN_ID`

Re-hash the JSONL and compare it to an existing manifest from **`replayt seal`** or from **`export-run` / `bundle-export --seal`** (`replayt.export_seal.v1`). Default manifest path is `<log-dir>/<run_id>.seal.json`. Use **`--manifest`** / **`--jsonl`** when you extracted **`events.seal.json`** and **`events.jsonl`** from a tarball (the export manifest records a relative **`jsonl_path`**). **`--output json`** prints **`replayt.verify_seal_report.v1`**. Exit **`0`** when digests match, **`1`** on mismatch, **`2`** on missing files or invalid manifest.

If project config defines **`verify_seal_hook`** or env **`REPLAYT_VERIFY_SEAL_HOOK`** is set, that command runs **after** digests match but **before** success output, with `REPLAYT_RUN_ID`, `REPLAYT_LOG_DIR`, `REPLAYT_VERIFY_SEAL_MANIFEST`, `REPLAYT_VERIFY_SEAL_JSONL`, `REPLAYT_VERIFY_SEAL_SCHEMA`, `REPLAYT_VERIFY_SEAL_LINE_COUNT`, and `REPLAYT_VERIFY_SEAL_FILE_SHA256` in the environment; non-zero exit turns a passing verify into exit **`1`** (no JSON report is printed on that path). Default **120s** wall-clock limit unless **`verify_seal_hook_timeout`** / **`REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT`** (`<= 0` = no limit). See [`CONFIG.md`](CONFIG.md).

## `replayt gc --older-than DURATION`

Delete JSONL run logs older than a duration (`90d`, `24h`, ...). `--dry-run` to preview.

## `replayt runs`

List recent local runs. **`--status completed|failed|paused|unknown`** (repeatable; OR semantics) filters on the best-effort terminal status derived from JSONL the same way as the listing columns (`unknown` when the log has no `run_completed` / `run_paused` yet). `--tag key=value` (repeatable) to filter. `--run-meta key=value` (repeatable) filters on `run_started.run_metadata` (string equality). **`--experiment key=value`** filters on `run_started.experiment`. **`--tool NAME`** (repeatable; OR) keeps runs that recorded at least one JSONL **`tool_call`** whose payload **`name`** equals **`NAME`** (exact string match). **`--structured-schema NAME`** (repeatable; OR) keeps runs that logged at least one **`structured_output`** or **`structured_output_failed`** whose payload **`schema_name`** equals **`NAME`**. **`--note-kind KIND`** (repeatable; OR) keeps runs that recorded at least one **`step_note`** whose payload **`kind`** equals **`KIND`**. Filter families **`--tool`**, **`--structured-schema`**, and **`--note-kind`** all apply when passed (AND between families).

## `replayt stats [--days N] [--tag key=value] [--run-meta key=value] [--experiment key=value] [--tool NAME] [--structured-schema NAME] [--note-kind KIND] [--output text|json]`

Aggregate counts, average `llm_response` latency, token usage, top failure states, event time range. **`--output json`** emits **`replayt.stats_report.v1`**. **`--tool`**, **`--structured-schema`**, and **`--note-kind`** use the same filters as **`replayt runs`**.

## `replayt doctor`

Check install, env vars, optional YAML extra, default provider connectivity, and best-effort filesystem readiness for the resolved `log_dir` / optional SQLite mirror path. `doctor` also reports soft trust-boundary warnings for risky defaults such as remote plain-HTTP base URLs, embedded credentials in `OPENAI_BASE_URL`, `log_mode=full`, a missing approval-reason policy for paused-run resumes, (on POSIX) a **`log_dir`** that is world-readable or world-writable, and (on POSIX) **`.env`** files under the current working directory or next to the discovered project config file when those files are world-readable or world-writable (paths and mode bits only; contents are not read). When project config sets **`min_replayt_version`**, `doctor` adds **`project_config_min_replayt_version`**: it is **healthy only** when the installed package meets that floor (or the constraint is unset); invalid constraint strings fail this check too. JSON output includes **`credential_env`**: a fixed list of common third-party LLM credential variable names each with boolean **`present`** (never values), plus a soft **`credential_env_extra_providers`** check when non-`OPENAI_API_KEY` entries from that list are non-empty in the process environment (replayt's default client does not read them). It also includes **`ci_artifacts`** plus readiness checks for env-driven CI outputs (`REPLAYT_JUNIT_XML`, `REPLAYT_SUMMARY_JSON`, and `REPLAYT_GITHUB_SUMMARY` / `GITHUB_STEP_SUMMARY`), so a missing parent directory or missing GitHub summary sink can fail preflight before the workflow runs. Optional **`--target TARGET`** plus **`--strict-graph`** / **`--inputs-json`** / **`--inputs-file`** (or default inputs from **`REPLAYT_INPUTS_FILE`** / project **`inputs_file`** when those flags are omitted) / repeatable **`--input key=value`** preflight-loads a workflow and runs the same graph/input validation as `replayt validate` without executing it. **`--format json`** prints `replayt.doctor_report.v1` with a **`healthy`** boolean: exit `0` when healthy, `1` otherwise. **`healthy`** ignores missing **`openai_api_key`**, missing project config, and these soft trust warnings so CI can validate graphs without secrets; other checks (including **`yaml_extra`**, **`provider_connectivity`** unless `--skip-connectivity`, path-readiness failures, CI artifact readiness failures, **`project_config_min_replayt_version`** when **`min_replayt_version`** is set, and optional `target_validation`) must pass.

## `replayt config`

Print the effective CLI defaults after CLI flags, project config, and environment variables are resolved. `--format json` emits `replayt.config_report.v1` with the resolved log paths, mirror policy, run/resume/export/seal/**`verify_seal`** policy-hook settings, redaction keys, approval-actor requirements, approval-reason policy, **`run.default_inputs_file`** / **`run.default_inputs_file_source`** (effective default inputs path when CLI omits **`--inputs-json`** and **`--inputs-file`**), **`project_config.unknown_keys`** for typo detection (unsupported keys are ignored; see [`CONFIG.md`](CONFIG.md#unknown-keys)), optional **`min_replayt_version`** / **`min_replayt_version_satisfied`** / **`replayt_version_installed`** when the repo pins a minimum package version (see [`CONFIG.md`](CONFIG.md)), trust-boundary warnings (including POSIX **`log_dir`** and **`.env`** permission hints when applicable), filesystem-readiness checks for the effective log / SQLite destinations, a **`ci_artifacts`** section previewing env-driven CI outputs (`REPLAYT_JUNIT_XML`, `REPLAYT_SUMMARY_JSON`, `REPLAYT_GITHUB_SUMMARY` / `GITHUB_STEP_SUMMARY`), the active provider/base URL/model plus source labels such as `project_config:model` or `env:OPENAI_BASE_URL`, and **`llm.credential_env`** (same presence-only name list as **`replayt doctor`** JSON). `replayt doctor` also reports a soft **`policy_hooks_external_code`** warning when trusted external hook subprocesses are configured. Text output may print a **`credential_env_note`** when extra vendor credential env vars are set but not consumed by replayt's OpenAI-compat client.

## `replayt version`

Print the installed **replayt** package version, Python runtime, and OS platform. **`--format json`** emits **`replayt.version_report.v1`** with structured Python version fields plus a map of **stable `schema` ids** used by other JSON CLI outputs (`run`, `inspect`, `stats`, `diff`, `contract`, `contract --check`, `validate`, `doctor`, `config`, `ci` summary, and packaged-example helpers) so CI matrices and wrappers can probe compatibility without scraping human text. Exit **0** always.
