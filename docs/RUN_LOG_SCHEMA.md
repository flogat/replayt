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
- `model` (string)
- `messages_summary` (object) — counts / roles, not full text unless logging mode is `full`

### `llm_response`

- `state` (string)
- `model` (string)
- `usage` (object, optional)
- `content_preview` (string, optional) — truncated unless `full` mode

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

### `run_failed`

- `error` (string)
- `state` (string | null)

## Logging modes

- **`redacted` (default)**: message bodies are not stored; only summaries and structured outputs as configured.
- **`full`**: full message content in `llm_request` / `llm_response` payloads — opt-in only.

## SQLite

Optional SQLite store mirrors the same events in table `events(run_id, seq, type, payload_json, ts)`.
