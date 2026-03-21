# Project configuration (CLI defaults)

The CLI walks **up** from the current working directory. At **each** directory it checks, in order:

1. **`.replaytrc.toml`** — if this file exists here, its supported keys become the project config and the walk **stops** (even if `pyproject.toml` is also present in the same folder).
2. Else **`pyproject.toml`** with **`[tool.replayt]`** — if that table exists, it is used and the walk **stops**.
3. Else continue to the parent directory.

So you get **one** config file: the nearest ancestor that defines either `.replaytrc.toml` or `[tool.replayt]`. See [`src/replayt/cli/main.py`](../src/replayt/cli/main.py) for the implementation.

## Supported keys

| Key | Purpose |
|-----|---------|
| `log_dir` | Default JSONL directory (string path), used when you omit `--log-dir` on the CLI default of `.replayt/runs`. Relative paths are resolved from the config file's directory. |
| `log_mode` | Default log mode: `redacted`, `structured_only`, or `full`. |
| `sqlite` | Optional path to SQLite mirror file. Relative paths are resolved from the config file's directory. |
| `provider` | Preset name for base URL/model (`openai`, `ollama`, `groq`, …)—same idea as `REPLAYT_PROVIDER`. |
| `model` | Default model name. |
| `timeout` | LLM HTTP timeout (seconds). |
| `strict_mirror` | If **true**, any SQLite mirror write failure aborts the run after logging. This is **not** cross-store atomicity: the JSONL primary may already contain the event that SQLite missed, so repair or re-sync may still be required. If **false**, the JSONL primary still records events but the mirror may miss rows until you repair or re-sync—do not treat SQLite as authoritative until you understand this mode. **Default:** when omitted, the CLI uses **strict** mirroring whenever `--sqlite` is set (or `sqlite` is set in project config); set `strict_mirror = false` explicitly to allow a lenient mirror. |
| `resume_hook` | Optional argv list for a subprocess run **before** `replayt resume` appends `approval_resolved` (policy gate). Example: `["python", "scripts/check_resume.py"]`. Override with env `REPLAYT_RESUME_HOOK` (shell tokenized; see [`CLI.md`](CLI.md)). Treat like shell commands: **trusted config only**, not untrusted user input. |
| `resume_hook_timeout` | Wall-clock seconds for that subprocess (default **120** if unset). Env `REPLAYT_RESUME_HOOK_TIMEOUT` overrides; value **≤ 0** means **no limit** (same as unlimited hook runtime—use only when intentional). |

## `Workflow.meta` — `llm_defaults`

If you set `meta={"llm_defaults": {"experiment": {"cohort": "A"}, ...}}` on `Workflow`, those keys merge into `LLMBridge` defaults (and appear under `effective` on `llm_request` events). The `llm_defaults` key is **not** copied into `workflow_meta` on `run_started` so audit metadata stays separate from workflow labels.

You can also pass `Workflow(..., llm_defaults={...})` in Python; same merge rules.

## Example `pyproject.toml`

```toml
[tool.replayt]
log_dir = ".replayt/runs"
log_mode = "redacted"
provider = "openrouter"
timeout = 120
```

## Example `.replaytrc.toml`

```toml
log_dir = "var/replayt"
strict_mirror = false
```

Environment variables and explicit CLI flags still override these defaults when you pass them.

For path-valued config keys such as `log_dir` and `sqlite`, relative paths are interpreted relative to the
config file that declared them, not the shell's current working directory. That keeps runs launched from
subdirectories writing to the same project-owned locations.

## `REPLAYT_RESUME_HOOK_TIMEOUT`

Seconds for the optional resume gate subprocess (`resume_hook` / `REPLAYT_RESUME_HOOK`). Overrides `resume_hook_timeout` from project config. **≤ 0** disables the timeout.

## `REPLAYT_LLM_MAX_RESPONSE_BYTES`

Upper bound on the HTTP body size for `/chat/completions` (default **32 MiB**). Parsed from env as a positive integer (minimum **1024** when set). Prevents unbounded memory use on huge or hostile responses. Invalid values raise a clear error at startup.

## `REPLAYT_LLM_MAX_SCHEMA_CHARS`

Upper bound on the serialized JSON Schema size embedded in `LLMBridge.parse` system prompts (default **250_000** characters). Parsed as a positive integer (minimum **1024** when set). Raise the limit or shrink the Pydantic model when you hit this guard.

## `REPLAYT_LOG_DIR`

If set, used as the default JSONL root when you omit `--log-dir` (i.e. when the CLI would otherwise use `.replayt/runs`). `[tool.replayt] log_dir` in project config still wins over this env var when you use the default `--log-dir` placeholder.

Use **`--log-subdir NAME`** (a single path segment, no slashes) to append a tenant- or job-specific subdirectory under the resolved root—handy for **one tenant → one log directory** layouts (see [`PRODUCTION.md`](PRODUCTION.md)).
