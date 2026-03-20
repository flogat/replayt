# Project configuration (CLI defaults)

The CLI walks **up** from the current working directory. At **each** directory it checks, in order:

1. **`.replaytrc.toml`** — if this file exists here, its supported keys become the project config and the walk **stops** (even if `pyproject.toml` is also present in the same folder).
2. Else **`pyproject.toml`** with **`[tool.replayt]`** — if that table exists, it is used and the walk **stops**.
3. Else continue to the parent directory.

So you get **one** config file: the nearest ancestor that defines either `.replaytrc.toml` or `[tool.replayt]`. See [`src/replayt/cli/main.py`](../src/replayt/cli/main.py) for the implementation.

## Supported keys

| Key | Purpose |
|-----|---------|
| `log_dir` | Default JSONL directory (string path), used when you omit `--log-dir` on the CLI default of `.replayt/runs`. |
| `log_mode` | Default log mode: `redacted`, `structured_only`, or `full`. |
| `sqlite` | Optional path to SQLite mirror file. |
| `provider` | Preset name for base URL/model (`openai`, `ollama`, `groq`, …)—same idea as `REPLAYT_PROVIDER`. |
| `model` | Default model name. |
| `timeout` | LLM HTTP timeout (seconds). |
| `strict_mirror` | If true, SQLite mirror write failures surface; if false, mirror errors are logged and the run continues (best-effort mirror). |

## Example `pyproject.toml`

```toml
[tool.replayt]
log_dir = ".replayt/runs"
log_mode = "redacted"
provider = "openai"
timeout = 120
```

## Example `.replaytrc.toml`

```toml
log_dir = "var/replayt"
strict_mirror = false
```

Environment variables and explicit CLI flags still override these defaults when you pass them.

## `REPLAYT_LOG_DIR`

If set, used as the default JSONL root when you omit `--log-dir` (i.e. when the CLI would otherwise use `.replayt/runs`). `[tool.replayt] log_dir` in project config still wins over this env var when you use the default `--log-dir` placeholder.

Use **`--log-subdir NAME`** (a single path segment, no slashes) to append a tenant- or job-specific subdirectory under the resolved root—handy for **one tenant → one log directory** layouts (see [`PRODUCTION.md`](PRODUCTION.md)).
