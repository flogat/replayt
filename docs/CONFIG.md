# Project configuration (CLI defaults)

The CLI walks up from the current working directory. At each directory it checks, in order:

1. `.replaytrc.toml`. If this file exists here, its supported keys become the project config and the walk stops, even if `pyproject.toml` is also present in the same folder.
2. Else `pyproject.toml` with `[tool.replayt]`. If that table exists, it is used and the walk stops.
3. Else continue to the parent directory.

So you get one config file: the nearest ancestor that defines either `.replaytrc.toml` or `[tool.replayt]`. See [`src/replayt/cli/main.py`](../src/replayt/cli/main.py) for the implementation.

`replayt init` and `replayt try --copy-to DIR` now create a local `.replaytrc.toml` with `target` and `inputs_file` so a freshly scaffolded directory can use plain `replayt run` / `replayt ci` without extra flags.

## Supported keys

| Key | Purpose |
|-----|---------|
| `log_dir` | Default JSONL directory (string path), used when you omit `--log-dir` on the CLI default of `.replayt/runs`. Relative paths are resolved from the config file's directory. |
| `log_mode` | Default log mode: `redacted`, `structured_only`, or `full`. |
| `redact_keys` | Optional list of structured field names to scrub from logged payloads (`run_started.inputs`, `structured_output.data`, tool payloads, approval details, snapshots, and similar). Matching is case-insensitive. |
| `sqlite` | Optional path to SQLite mirror file. Relative paths are resolved from the config file's directory. |
| `provider` | Preset name for base URL/model (`openai`, `ollama`, `groq`, and similar), same idea as `REPLAYT_PROVIDER`. |
| `model` | Default model name. |
| `target` | Default workflow target for **`replayt run`** / **`replayt ci`** when you omit the **`TARGET`** positional argument: a `module:variable` string or a path to `workflow.py` / YAML (same forms as the CLI). Env **`REPLAYT_TARGET`** overrides this when set. Other commands (**`resume`**, **`validate`**, **`graph`**, **`contract`**, **`doctor --target`**) still require an explicit target. |
| `inputs_file` | Default path to a UTF-8 JSON **object** file merged into run inputs when you omit **`--inputs-json`** and **`--inputs-file`** on **`replayt run`**, **`replayt ci`**, **`replayt validate`**, and on **`replayt doctor --target`**. Relative paths resolve from the config file's directory. Env **`REPLAYT_INPUTS_FILE`** overrides this when set (see below). **`replayt try`** does **not** read this default (it uses packaged example payloads unless you pass **`--inputs-json`** / **`--inputs-file`**). |
| `timeout` | LLM HTTP timeout (seconds). |
| `strict_mirror` | If true, any SQLite mirror write failure aborts the run after logging. This is not cross-store atomicity: the JSONL primary may already contain the event that SQLite missed, so repair or re-sync may still be required. If false, the JSONL primary still records events but the mirror may miss rows until you repair or re-sync. Do not treat SQLite as authoritative until you understand this mode. Default: when omitted, the CLI uses strict mirroring whenever `--sqlite` is set (or `sqlite` is set in project config); set `strict_mirror = false` explicitly to allow a lenient mirror. |
| `run_hook` | Optional argv list for a subprocess run before `replayt run` / `replayt ci` starts execution. replayt passes `REPLAYT_TARGET`, `REPLAYT_RUN_ID`, `REPLAYT_RUN_MODE`, `REPLAYT_LOG_DIR`, `REPLAYT_LOG_MODE`, `REPLAYT_DRY_RUN`, optional `REPLAYT_SQLITE`, and normalized JSON object strings in `REPLAYT_RUN_INPUTS_JSON`, `REPLAYT_RUN_TAGS_JSON`, `REPLAYT_RUN_METADATA_JSON`, and `REPLAYT_RUN_EXPERIMENT_JSON` when those values are present. Override with env `REPLAYT_RUN_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Successful runs record a compact breadcrumb under `run_started.runtime.policy_hooks.run`. Treat like shell commands: trusted config only, not untrusted user input. |
| `run_hook_timeout` | Wall-clock seconds for that subprocess (default 120 if unset). Env `REPLAYT_RUN_HOOK_TIMEOUT` overrides; value `<= 0` means no limit. |
| `resume_hook` | Optional argv list for a subprocess run before `replayt resume` appends `approval_resolved` (policy gate). Example: `["python", "scripts/check_resume.py"]`. Override with env `REPLAYT_RESUME_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Successful resumes record a compact breadcrumb under `approval_resolved.policy_hook`. Treat like shell commands: trusted config only, not untrusted user input. |
| `resume_hook_timeout` | Wall-clock seconds for that subprocess (default 120 if unset). Env `REPLAYT_RESUME_HOOK_TIMEOUT` overrides; value `<= 0` means no limit. |
| `export_hook` | Optional argv list for a subprocess run before `replayt export-run` or `replayt bundle-export` writes the archive (policy / DLP gate). replayt passes `REPLAYT_RUN_ID`, `REPLAYT_EXPORT_KIND` (`export_run` or `bundle_export`), `REPLAYT_LOG_DIR`, `REPLAYT_EXPORT_MODE`, `REPLAYT_EXPORT_OUT`, `REPLAYT_EXPORT_SEAL`, `REPLAYT_EXPORT_EVENT_COUNT`, optional `REPLAYT_SQLITE`, and `REPLAYT_BUNDLE_REPORT_STYLE` for bundle exports. Override with env `REPLAYT_EXPORT_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Successful exports record a compact `policy_hook` object in the export manifest. Trusted config only, not untrusted user input. |
| `export_hook_timeout` | Wall-clock seconds for that subprocess (default 120 if unset). Env `REPLAYT_EXPORT_HOOK_TIMEOUT` overrides; value `<= 0` means no limit. |
| `seal_hook` | Optional argv list for a subprocess run after the JSONL is read and digests are computed but **before** `replayt seal` writes the manifest (policy gate for standalone seals; tarball exports still use `export_hook`). replayt passes `REPLAYT_RUN_ID`, `REPLAYT_LOG_DIR`, `REPLAYT_SEAL_JSONL`, `REPLAYT_SEAL_OUT`, and `REPLAYT_SEAL_LINE_COUNT`. Override with env `REPLAYT_SEAL_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Successful seals record a compact `policy_hook` object in the seal manifest. Trusted config only, not untrusted user input. |
| `seal_hook_timeout` | Wall-clock seconds for that subprocess (default 120 if unset). Env `REPLAYT_SEAL_HOOK_TIMEOUT` overrides; value `<= 0` means no limit. |
| `verify_seal_hook` | Optional argv list for a subprocess run after **`replayt verify-seal`** confirms digests match but **before** it prints success output (policy / audit gate). replayt passes `REPLAYT_RUN_ID`, `REPLAYT_LOG_DIR`, `REPLAYT_VERIFY_SEAL_MANIFEST`, `REPLAYT_VERIFY_SEAL_JSONL`, `REPLAYT_VERIFY_SEAL_SCHEMA` (manifest `schema` id), `REPLAYT_VERIFY_SEAL_LINE_COUNT`, and `REPLAYT_VERIFY_SEAL_FILE_SHA256`. Override with env `REPLAYT_VERIFY_SEAL_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Trusted config only, not untrusted user input. |
| `verify_seal_hook_timeout` | Wall-clock seconds for that subprocess (default 120 if unset). Env `REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT` overrides; value `<= 0` means no limit. |
| `approval_actor_required_keys` | Optional list of keys that must exist on `replayt resume --actor-json ...` before replayt will append `approval_resolved`. Use this for audit fields such as `email`, `ticket_id`, or change-control ids. |
| `min_replayt_version` | Optional minimum installed **replayt** package version for this repository (string such as `0.4.7`). Comparison uses the leading numeric `major.minor.patch` prefix (same style as replayt releases), not full PEP 440 semantics. When set, most CLI commands fail fast if the installed package is older; **`replayt config`**, **`replayt version`**, **`replayt doctor`**, and **`replayt init`** still run so you can inspect or refresh the install. |
| `approval_reason_required` | Optional boolean. When `true`, `replayt resume` requires a non-empty `--reason` before replayt will append `approval_resolved`. Use this when every approval or rejection needs a written justification in the audit trail. |

## Unknown keys

Any other top-level key under `[tool.replayt]` (or in `.replaytrc.toml`) is **ignored** so a typo does not crash the CLI, but it also does nothing. Run `replayt config --format json` and read `project_config.unknown_keys`, or `replayt doctor`, to see names that are not in the supported table above. Those are usually a hyphen/underscore mix-up (`log-mode` vs `log_mode`) or a mistaken key copied from another tool.

### CI: fail on unknown keys

In a job that already has Python, fail the step when unsupported keys are present (non-empty `unknown_keys`):

```bash
replayt config --format json | python -c "import json,sys; u=json.load(sys.stdin)['project_config'].get('unknown_keys',[]); print(u); sys.exit(1 if u else 0)"
```

## `Workflow.meta` and `llm_defaults`

If you set `meta={"llm_defaults": {"experiment": {"cohort": "A"}, "stop": ["###"], "extra_body": {"reasoning": {"effort": "low"}}, ...}}` on `Workflow`, those keys merge into `LLMBridge` defaults (and appear under `effective` on `llm_request` events). The `llm_defaults` key is not copied into `workflow_meta` on `run_started` so audit metadata stays separate from workflow labels.

You can also pass `Workflow(..., llm_defaults={...})` in Python; same merge rules.

## Example `pyproject.toml`

```toml
[tool.replayt]
log_dir = ".replayt/runs"
log_mode = "redacted"
redact_keys = ["email", "token"]
provider = "ollama"
timeout = 120
```

## Example `.replaytrc.toml`

```toml
log_dir = "var/replayt"
strict_mirror = false
approval_actor_required_keys = ["email", "ticket_id"]
approval_reason_required = true
```

Environment variables and explicit CLI flags still override these defaults when you pass them.

Run `replayt config --format json` to inspect the resolved values, best-effort filesystem readiness for the effective `log_dir` / `sqlite` paths, env-driven CI artifact sinks (`REPLAYT_JUNIT_XML`, `REPLAYT_SUMMARY_JSON`, `REPLAYT_GITHUB_SUMMARY` / `GITHUB_STEP_SUMMARY`), and where each setting came from (`project_config:*`, `env:*`, or a built-in default/preset). That is the quickest way to confirm what a CI job or repo-local shell will actually use before the workflow starts writing logs. The JSON report includes trust-boundary warnings for POSIX log directories and nearby `.env` files that are group- or world-readable/writable, plus **`project_config.min_replayt_version`** (when set), **`min_replayt_version_satisfied`**, and the installed package version so CI can assert the constraint without running a workflow.

For path-valued config keys such as `log_dir` and `sqlite`, relative paths are interpreted relative to the config file that declared them, not the shell's current working directory. That keeps runs launched from subdirectories writing to the same project-owned locations.

## `REPLAYT_RUN_HOOK_TIMEOUT`

Seconds for the optional pre-run policy subprocess (`run_hook` / `REPLAYT_RUN_HOOK`). Overrides `run_hook_timeout` from project config. `<= 0` disables the timeout.

## `REPLAYT_RESUME_HOOK_TIMEOUT`

Seconds for the optional resume gate subprocess (`resume_hook` / `REPLAYT_RESUME_HOOK`). Overrides `resume_hook_timeout` from project config. `<= 0` disables the timeout.

## `REPLAYT_EXPORT_HOOK_TIMEOUT`

Seconds for the optional pre-export policy subprocess (`export_hook` / `REPLAYT_EXPORT_HOOK`). Overrides `export_hook_timeout` from project config. `<= 0` disables the timeout.

## `REPLAYT_SEAL_HOOK_TIMEOUT`

Seconds for the optional pre-seal policy subprocess (`seal_hook` / `REPLAYT_SEAL_HOOK`). Overrides `seal_hook_timeout` from project config. `<= 0` disables the timeout.

## `REPLAYT_VERIFY_SEAL_HOOK_TIMEOUT`

Seconds for the optional post-verify policy subprocess (`verify_seal_hook` / `REPLAYT_VERIFY_SEAL_HOOK`). Overrides `verify_seal_hook_timeout` from project config. `<= 0` disables the timeout.

## `REPLAYT_LLM_MAX_RESPONSE_BYTES`

Upper bound on the HTTP body size for `/chat/completions` (default 32 MiB). Parsed from env as a positive integer (minimum 1024 when set). Prevents unbounded memory use on huge or hostile responses. Invalid values raise a clear error at startup.

## `REPLAYT_LLM_MAX_SCHEMA_CHARS`

Upper bound on the serialized JSON Schema size embedded in `LLMBridge.parse` system prompts (default `250_000` characters). Parsed as a positive integer (minimum `1024` when set). Raise the limit or shrink the Pydantic model when you hit this guard.

## `REPLAYT_CI_METADATA_JSON`

When **`replayt run`** / **`replayt ci`** writes a machine-readable summary (**`--summary-json`** or env **`REPLAYT_SUMMARY_JSON`**), you may set this variable to a JSON **object** (string keys, JSON-serializable values). replayt parses it before the workflow starts; invalid JSON or a non-object (array, string, `null`, …) aborts with exit code **`1`** and does not run the workflow. Parsed content is copied into the summary file under **`ci_metadata`** so downstream alerts and ticket bots can correlate **`run_id`** with pipeline identifiers you choose (for example **`CI_PIPELINE_URL`** / **`GITHUB_SHA`** mapped in shell).

If no summary path is configured, this variable is ignored even when set.

## `REPLAYT_JUNIT_XML`

When set to a non-empty path, **`replayt run`** writes the same minimal JUnit XML artifact as **`replayt ci --junit-xml PATH`**. `replayt config --format json` exposes the resolved path under **`ci_artifacts.junit_xml`**, and `replayt doctor --format json` adds **`ci_junit_xml_ready`** so a CI shell can catch a missing or unwritable parent directory before the workflow starts.

## `REPLAYT_SUMMARY_JSON`

When set to a non-empty path, **`replayt run`** writes the same **`replayt.ci_run_summary.v1`** JSON artifact as **`replayt ci --summary-json PATH`**. `replayt config --format json` exposes the resolved path under **`ci_artifacts.summary_json`**, and `replayt doctor --format json` adds **`ci_summary_json_ready`** so a broken artifact path fails preflight instead of only failing after execution.

## `REPLAYT_GITHUB_SUMMARY`

Set to **`1`** to request the same markdown summary behavior as **`replayt ci --github-summary`**. replayt only appends when the CI runner also exports **`GITHUB_STEP_SUMMARY`** with a writable file path. `replayt config --format json` shows both the request bit and the sink path under **`ci_artifacts.github_summary`**, while `replayt doctor --format json` reports **`ci_github_summary_ready`** when the request is enabled but the sink env var is missing or unusable.

## `GITHUB_STEP_SUMMARY`

GitHub Actions populates this env var with the markdown summary file path for the current step. replayt does not invent a fallback path when it is absent: if you request GitHub summaries via **`--github-summary`** or **`REPLAYT_GITHUB_SUMMARY=1`**, export **`GITHUB_STEP_SUMMARY`** from the runner (GitHub does this automatically inside Actions). `replayt config --format json` shows the resolved sink path under **`ci_artifacts.github_summary.path`**.

## `REPLAYT_STEP_SUMMARY`

When **`replayt run`** / **`replayt ci`** appends a markdown step summary (**`--github-summary`** or env **`REPLAYT_GITHUB_SUMMARY=1`**), this variable may hold a **file path** to append the same block when **`GITHUB_STEP_SUMMARY`** is unset (for example GitLab, Buildkite, or local CI scripts). Parent directories are created as needed. If both **`GITHUB_STEP_SUMMARY`** and **`REPLAYT_STEP_SUMMARY`** are set, **`GITHUB_STEP_SUMMARY`** wins.

## `REPLAYT_TARGET`

When set to a non-empty string, used as the workflow **`TARGET`** for **`replayt run`** and **`replayt ci`** if you omit the positional argument. A **`TARGET` passed on the command line always wins**; **`[tool.replayt] target`** (or `.replaytrc.toml`) is the fallback when this env var is unset. Use **`replayt config --format json`** and read **`run.default_target`** / **`run.default_target_source`** to see what a shell or CI job would use.

## `REPLAYT_INPUTS_FILE`

When set to a non-empty path, used as the default inputs JSON file when you omit **`--inputs-json`** and **`--inputs-file`** on **`replayt run`**, **`replayt ci`**, **`replayt validate`**, and **`replayt doctor --target`**. The file must contain a single JSON **object** (same rules as **`--inputs-file`**). CLI flags always win; **`[tool.replayt] inputs_file`** (or `.replaytrc.toml`) is the fallback when this env var is unset. Use **`replayt config --format json`** and read **`run.default_inputs_file`** / **`run.default_inputs_file_source`**. This does **not** apply to **`replayt try`** (see the `inputs_file` row above).

## `REPLAYT_LOG_DIR`

If set, used as the default JSONL root when you omit `--log-dir` (that is, when the CLI would otherwise use `.replayt/runs`). `[tool.replayt] log_dir` in project config still wins over this env var when you use the default `--log-dir` placeholder.

Use `--log-subdir NAME` (a single path segment, no slashes) to append a tenant- or job-specific subdirectory under the resolved root, handy for one-tenant-per-log-directory layouts (see [`PRODUCTION.md`](PRODUCTION.md)).
