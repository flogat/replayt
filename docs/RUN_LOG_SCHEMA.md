# Run log event schema (JSONL)

Events are append-only, one JSON object per line. All events share:

| Field     | Type   | Description |
|-----------|--------|-------------|
| `ts`      | string | ISO 8601 UTC timestamp |
| `run_id`  | string | UUID for the run |
| `seq`     | int    | Monotonic sequence number per run |
| `type`    | string | Event kind (see below) |
| `payload` | object | Event-specific data |

## Event types

### `run_started`

- `workflow_name` (string)
- `workflow_version` (string)
- `initial_state` (string)
- `inputs` (object, optional) — may be redacted
- `tags` (object, optional) — string key/value pairs from CLI `--tag`
- `run_metadata` (object, optional) — JSON-serializable bag from CLI `--metadata-json` or `Runner.run(..., run_metadata={...})` (experiment ids, prompt versions, etc.); filter listings with `replayt runs --run-meta key=value` (string equality on `str(value)`).
- `workflow_meta` (object, optional) — JSON-serializable bag from `Workflow(..., meta={...})` (e.g. package id, git SHA)

### `state_entered`

- `state` (string)

### `state_exited`

- `state` (string)
- `next_state` (string | null) — `null` if terminal

### `transition`

- `from_state` (string)
- `to_state` (string)
- `reason` (string, optional)

### `llm_request`

- `state` (string)
- `effective` (object) — resolved settings for this call (always logged): `model`, `temperature`, `max_tokens`, `timeout_seconds`, `extra_header_names` (header **names** only, never values), optional `experiment` (object) from `ctx.llm.with_settings(experiment={...})` (merged across chained `with_settings` calls)
- `messages_summary` (object) — counts / roles when logging mode is not `full`
- `messages` (array) — only when logging mode is `full`

### `llm_response`

- `state` (string)
- `model` (string)
- `usage` (object, optional)
- `effective` (object) — same shape as on `llm_request` for this round trip
- `content_preview` (string, optional) — truncated in `redacted` mode only
- `content` (string) — only when logging mode is `full`

### `structured_output`

- `state` (string)
- `schema_name` (string)
- `data` (object) — validated model dump

### `tool_call`

- `state` (string)
- `name` (string)
- `arguments` (object)

### `tool_result`

- `state` (string)
- `name` (string)
- `ok` (bool)
- `result` (object | string | null)
- `error` (string | null)

### `retry_scheduled`

- `state` (string)
- `attempt` (int)
- `max_attempts` (int)
- `error` (string)

### `approval_requested`

- `approval_id` (string)
- `state` (string)
- `summary` (string)
- `details` (object, optional)

### `approval_resolved`

- `approval_id` (string)
- `approved` (bool)
- `resolver` (string, optional)

### `run_paused`

- `reason` (string) — e.g. `approval_required`
- `approval_id` (string, optional)

### `run_completed`

- `final_state` (string | null)
- `status` (string) — `completed` | `failed`

**Failed runs:** The runner emits a `run_failed` event first (structured error detail), then a final `run_completed` with `status: "failed"`. Use `run_failed` for diagnostics; use `run_completed` for a single “run ended” marker across success and failure.

### `run_failed`

- `error` (object) — serialized exception: `type`, `module`, `message`, optional `traceback`
- `state` (string | null)

## Logging modes

- **`redacted` (default)**: message bodies are not stored; only summaries and structured outputs as configured. LLM responses may include a short `content_preview`.
- **`structured_only`**: like `redacted`, but **no** `content_preview` on `llm_response` — rely on `structured_output` events for audit.
- **`full`**: full message content in `llm_request` / `llm_response` payloads — opt-in only.

## SQLite

Optional SQLite store mirrors the same events in table `events(run_id, seq, type, payload_json, ts)`.

## Export bundle (`replayt export-run`)

Not a raw JSONL file on disk: the CLI can write a **`.tar.gz`** containing `events.jsonl` (optionally sanitized to match `redacted` / `structured_only` / `full` export semantics) plus `manifest.json` with `schema: "replayt.export_bundle.v1"` and `events_jsonl_sha256`. Use this when sharing runs outside the original log directory.

## Seal sidecar (`replayt seal`)

Not a JSONL line: the CLI can write `<run_id>.seal.json` next to `<run_id>.jsonl` with `schema: "replayt.seal.v1"`, `line_sha256` (one digest per raw line, including newlines where present), and `file_sha256` for the whole file. See [`CLI.md`](CLI.md).
