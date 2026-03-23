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
- `workflow.contract_schema`
- `workflow.contract_sha256`: stable SHA-256 fingerprint of `Workflow.contract()` without re-running the workflow
- `llm.client_class`
- non-secret LLM settings such as `provider`, `base_url`, `model`, `top_p`, `frequency_penalty`, `presence_penalty`, `seed`, `extra_body_keys`, `http_retries`, timeouts, and whether an API key was present
- `trust_boundary.warnings`: soft local-policy findings such as `log_mode=full` or a risky `OPENAI_BASE_URL`
- `policy_hooks.run` / `policy_hooks.resume` (object, optional): compact CLI policy-hook breadcrumbs with `source`, `argv0`, and `arg_count` when trusted external gate subprocesses were configured for the run lifecycle

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
- `effective` (object): resolved settings for this call, including `model`, `temperature`, `top_p`, optional `frequency_penalty` / `presence_penalty` / `seed` (omitted from the HTTP payload when null), optional `stop` (array of up to four strings; omitted from the HTTP payload when unset), optional `extra_body` (small provider-specific JSON fields merged into the request body), `max_tokens`, `timeout_seconds`, `base_url`, `extra_header_names`, optional `provider`, optional `structured_output_mode`, optional `call_label` (short caller-chosen tag from `ctx.llm.with_settings(call_label=...)` when one handler issues multiple LLM calls), optional `experiment`, and optional compact `response_format` (OpenAI-style `type` plus optional `json_schema_name` / `json_schema_strict` when the gateway request includes `response_format`; omits the full embedded JSON Schema tree)
- `call_label` (string, optional): duplicate of `effective.call_label` when set, for quick `jq` filters alongside `schema_name`
- `schema_name` (string, optional): Pydantic model class name for `ctx.llm.parse(...)` calls (same string as on `structured_output` / `structured_output_failed`); also set when `ctx.llm.complete_text(..., schema_name=...)` tags a freeform completion; otherwise omitted
- `messages_sha256` (string): stable SHA-256 fingerprint of the exact message list sent to the provider
- `effective_sha256` (string): stable SHA-256 fingerprint of the logged `effective` settings object
- `schema_sha256` (string, optional): stable SHA-256 fingerprint of `model_type.model_json_schema()` for `ctx.llm.parse(...)`
- `messages_summary` (object): counts and roles when logging mode is not `full`
- `messages` (array): only when logging mode is `full`

### `llm_response`

- `state` (string)
- `model` (string)
- `usage` (object, optional)
- `effective` (object): same shape as on `llm_request`
- `call_label` (string, optional): same as on `llm_request` when present
- `schema_name` (string, optional): same as on `llm_request` when present (parse traffic or tagged `complete_text`)
- `messages_sha256` (string): same fingerprint as on `llm_request`
- `effective_sha256` (string): same fingerprint as on `llm_request`
- `schema_sha256` (string, optional): same fingerprint as on `llm_request` for structured parses
- `finish_reason` (string or null): first choice `finish_reason` from the provider when present (for example `stop`, `length`, `content_filter`); null when the gateway omits it
- `chat_completion_id` (string, optional): provider response `id` when the gateway returns one (useful to correlate with vendor dashboards)
- `system_fingerprint` (string, optional): provider fingerprint when returned (OpenAI-style reproducibility hint)
- `content_preview` (string, optional): truncated in `redacted` mode only
- `content` (string): only when logging mode is `full`

### `structured_output`

- `state` (string)
- `schema_name` (string)
- `call_label` (string, optional): same as on `llm_request` / `llm_response` when `effective.call_label` is set
- `data` (object): validated model dump
- `effective` (object): same shape as on `llm_request` / `llm_response` for this completion (model, sampling, timeouts, optional `experiment`, `structured_output_mode`, and so on) so analytics can filter on one event type without joining prior LLM lines
- `messages_sha256` (string): same fingerprint as the triggering `llm_request`
- `effective_sha256` (string): same fingerprint as the triggering `llm_request`
- `schema_sha256` (string): stable SHA-256 fingerprint of the parse schema
- `latency_ms` (integer): wall time for the provider round trip (same as the preceding `llm_response`)
- `usage` (object or null): token accounting from the provider when present (same shape as on `llm_response`)
- `finish_reason` (string or null): first choice `finish_reason` when the gateway returned one
- `chat_completion_id` (string, optional): provider response `id` when returned (correlate with vendor dashboards without joining `llm_response`)
- `system_fingerprint` (string, optional): provider fingerprint when returned

### `structured_output_failed`

- `state` (string)
- `schema_name` (string)
- `call_label` (string, optional): same as on `llm_request` when `effective.call_label` is set
- `stage` (string): for example `schema_limit`, `response_limit`, `json_extract`, `json_decode`, or `schema_validate`
- `structured_output_mode` (string): `prompt_only` or `native_json_schema`
- `error` (object): serialized exception with `type`, `module`, and `message`
- `effective` (object, optional): resolved LLM settings for the failed parse call (including `structured_output_mode`); for `schema_limit` failures this is still populated even though no `llm_request` was emitted (no giant system schema is hashed into `messages_sha256`)
- `messages_sha256` (string, optional): same fingerprint as the triggering `llm_request` when the provider call happened
- `effective_sha256` (string, optional): same fingerprint as the triggering `llm_request` when the provider call happened
- `schema_sha256` (string, optional): stable SHA-256 fingerprint of the parse schema
- `response_chars` (int, optional): response size when the failure happened after the provider returned text
- `validation_issues` (array, optional): when `stage` is `schema_validate` and the exception is Pydantic `ValidationError`, up to 32 entries with `type` (string or null), `loc` (array of string or integer path segments), and `msg` (string)
- `validation_issue_count` (int, optional): total Pydantic error count when `validation_issues` is present (may exceed the length of `validation_issues`)
- `validation_issues_truncated` (bool, optional): true when `validation_issue_count` is greater than the number of logged `validation_issues`

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

### `step_error`

- `state` (string): workflow step where the failure was classified
- `error` (object): serialized exception with `type`, `module`, `message`, and optional `traceback`

Emitted immediately before `run_failed` when a step handler exhausts retries, when `max_steps` is exceeded, when `before_step` / `after_step` hooks raise, or when context schema expectations fail (same `error` shape as on `run_failed`).

### `retry_scheduled`

- `state` (string)
- `attempt` (int)
- `max_attempts` (int)
- `error` (object): serialized exception with `type`, `module`, `message`, and optional `traceback`

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
- `policy_hook` (object, optional): compact breadcrumb with `source`, `argv0`, and `arg_count` when a trusted `resume_hook` subprocess allowed this approval decision

Project config `approval_actor_required_keys = [...]` or CLI `--require-actor-key` can require fixed `actor` keys before replayt writes `approval_resolved`. Project config `approval_reason_required = true` or CLI `--require-reason` can require a non-empty `reason`.

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

Not a raw JSONL file on disk: the CLI can write a `.tar.gz` containing `events.jsonl` (optionally sanitized to match `redacted`, `structured_only`, or `full` export semantics) plus `manifest.json` with `schema: "replayt.export_bundle.v1"` and `events_jsonl_sha256`. When an `export_hook` gate is active, `manifest.json` also includes a compact `policy_hook` object (`source`, `argv0`, `arg_count`). When you pass `--seal`, the archive also includes `events.seal.json` with `schema: "replayt.export_seal.v1"`, per-line SHA-256 digests, and a full-file digest for the exported `events.jsonl`.

## Seal sidecar (`replayt seal`)

Not a JSONL line: the CLI can write `<run_id>.seal.json` next to `<run_id>.jsonl` with `schema: "replayt.seal.v1"`, `line_sha256` (one digest per raw line, including newlines where present), and `file_sha256` for the whole file. When a `seal_hook` gate is active, the seal JSON also includes a compact `policy_hook` object (`source`, `argv0`, `arg_count`). See [`CLI.md`](CLI.md).
