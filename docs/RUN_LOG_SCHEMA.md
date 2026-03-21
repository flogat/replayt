# Run log schema

Each run is append-only JSONL: one JSON object per line, in order.

Common envelope keys on every line:

- `ts` (string): ISO 8601 UTC timestamp
- `run_id` (string)
- `seq` (int): monotonically increasing per run
- `type` (string): event kind
- `payload` (object): event-specific data

Use `replayt log-schema` for the bundled JSON Schema and this page for the main payload shapes.

## `run_started`

- `workflow_name` (string)
- `workflow_version` (string)
- `initial_state` (string)
- `inputs` (object, optional): may be redacted
- `tags` (object, optional): string key/value pairs from CLI `--tag`
- `run_metadata` (object, optional): JSON-serializable bag from CLI `--metadata-json` or `Runner.run(..., run_metadata={...})`
- `experiment` (object, optional): JSON-serializable bag from CLI `--experiment-json` or `Runner.run(..., experiment={...})`
- `workflow_meta` (object, optional): JSON-serializable bag from `Workflow(..., meta={...})`
- `runtime` (object, optional): safe execution snapshot recorded at run start

`runtime` currently includes:

- `engine.log_mode`
- `engine.max_steps`
- `engine.redact_keys`
- `hooks.before_step`
- `hooks.after_step`
- `store.class`
- `llm.client_class`
- non-secret LLM settings such as `provider`, `base_url`, `model`, `top_p`, `frequency_penalty`, `presence_penalty`, `seed`, timeouts, and whether an API key was present
- `trust_boundary.warnings`: soft local-policy findings such as `log_mode=full` or a risky `OPENAI_BASE_URL`

## State flow

### `state_entered`

- `state` (string)

### `state_exited`

- `state` (string)
- `next_state` (string or null)

### `transition`

- `from_state` (string)
- `to_state` (string)
- `reason` (string, optional)

## LLM events

### `llm_request`

- `state` (string)
- `effective` (object): resolved settings for this call, including `model`, `temperature`, `top_p`, optional `frequency_penalty` / `presence_penalty` / `seed` (omitted from the HTTP payload when null), `max_tokens`, `timeout_seconds`, `base_url`, `extra_header_names`, optional `provider`, optional `structured_output_mode`, and optional `experiment`
- `messages_summary` (object): counts and roles when logging mode is not `full`
- `messages` (array): only when logging mode is `full`

### `llm_response`

- `state` (string)
- `model` (string)
- `usage` (object, optional)
- `effective` (object): same shape as on `llm_request`
- `content_preview` (string, optional): truncated in `redacted` mode only
- `content` (string): only when logging mode is `full`

### `structured_output`

- `state` (string)
- `schema_name` (string)
- `data` (object): validated model dump

### `structured_output_failed`

- `state` (string)
- `schema_name` (string)
- `stage` (string): for example `schema_limit`, `response_limit`, `json_extract`, `json_decode`, or `schema_validate`
- `structured_output_mode` (string): `prompt_only` or `native_json_schema`
- `error` (object): serialized exception with `type`, `module`, and `message`
- `effective` (object, optional): resolved LLM settings for the failed parse call
- `response_chars` (int, optional): response size when the failure happened after the provider returned text

## Tool events

### `tool_call`

- `state` (string)
- `name` (string)
- `arguments` (object)

### `tool_result`

- `state` (string)
- `name` (string)
- `ok` (bool)
- `result` (object, string, or null)
- `error` (string or null)

## Application notes

### `step_note`

- `state` (string or null)
- `kind` (string): short label such as `framework_summary` or `subrun_link`
- `summary` (string, optional): human-readable breadcrumb
- `data` (object, array, string, number, bool, or null, optional): small JSON-serializable detail payload

Use `ctx.note(...)` inside a step when you want one explicit breadcrumb about framework composition, streaming summaries, or linked sub-runs without turning those systems into first-class runner semantics.

## Retry and failure

### `retry_scheduled`

- `state` (string)
- `attempt` (int)
- `max_attempts` (int)
- `error` (string)

### `run_failed`

- `error` (object): serialized exception with `type`, `module`, `message`, and optional `traceback`
- `state` (string or null)

### `run_completed`

- `final_state` (string or null)
- `status` (string): `completed` or `failed`

Failed runs emit `run_failed` first and then a final `run_completed` with `status: "failed"`.

## Approval events

### `approval_requested`

- `approval_id` (string)
- `state` (string)
- `summary` (string)
- `details` (object, optional)

### `approval_resolved`

- `approval_id` (string)
- `approved` (bool)
- `resolver` (string, optional): default `cli` from `replayt resume`
- `reason` (string, optional): audit note from `replayt resume --reason`
- `actor` (object, optional): JSON object from `replayt resume --actor-json`

Project config `approval_actor_required_keys = [...]` or CLI `--require-actor-key` can require fixed `actor` keys before replayt writes `approval_resolved`.

### `run_paused`

- `reason` (string), for example `approval_required`
- `approval_id` (string, optional)

## Logging modes

- `redacted` (default): message bodies are not stored; only summaries and structured outputs remain. LLM responses may include a short `content_preview`.
- `structured_only`: like `redacted`, but no `content_preview` on `llm_response`.
- `full`: full message content in `llm_request` and `llm_response`. Opt in only.

Use `--redact-key FIELD` (repeatable) or project config `redact_keys = [...]` to scrub matching structured field names from payloads that still remain under these modes.

## SQLite

Optional SQLite storage mirrors the same events in `events(run_id, seq, type, payload_json, ts)`.

## Export bundle (`replayt export-run`)

Not a raw JSONL file on disk: the CLI can write a `.tar.gz` containing `events.jsonl` (optionally sanitized to match `redacted`, `structured_only`, or `full` export semantics) plus `manifest.json` with `schema: "replayt.export_bundle.v1"` and `events_jsonl_sha256`. When you pass `--seal`, the archive also includes `events.seal.json` with `schema: "replayt.export_seal.v1"`, per-line SHA-256 digests, and a full-file digest for the exported `events.jsonl`.

## Seal sidecar (`replayt seal`)

Not a JSONL line: the CLI can write `<run_id>.seal.json` next to `<run_id>.jsonl` with `schema: "replayt.seal.v1"`, `line_sha256` (one digest per raw line, including newlines where present), and `file_sha256` for the whole file. See [`CLI.md`](CLI.md).
