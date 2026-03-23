# Recipes

Copyable operational snippets. For onboarding, use [`QUICKSTART.md`](QUICKSTART.md). For architecture boundaries, see [`PRODUCTION.md`](PRODUCTION.md).

## Configure the LLM client (base URL, model, timeouts)

replayt uses a small OpenAI-compatible HTTP client. Configure it at two levels: **process defaults** and **per-call overrides**.

**Environment (CLI and Python if you omit `llm_settings`):**

- `OPENAI_API_KEY` - optional for local Ollama; required for hosted live model calls
- `OPENAI_BASE_URL` - if unset, defaults to the **`REPLAYT_PROVIDER`** preset base URL, else **`http://127.0.0.1:11434/v1`**
- `REPLAYT_MODEL` - if unset, defaults to the **`REPLAYT_PROVIDER`** preset model, else **`llama3.2`**
- `REPLAYT_PROVIDER` - optional preset name: if unset, behavior matches **`ollama`**; explicit values: `openai`, `ollama`, `groq`, `together`, `openrouter`, `anthropic` (native Anthropic hosts often need an OpenAI-compatible gateway; see [`src/replayt_examples/README.md`](../src/replayt_examples/README.md))

**Python defaults** - pick a preset without memorizing URLs:

```python
import os

from replayt.llm import LLMSettings

LLMSettings.for_provider("ollama")  # local Ollama OpenAI-compat
LLMSettings.for_provider("groq", api_key=os.environ["GROQ_API_KEY"])
```

**`Runner` in Python** - pass `llm_settings` for a non-default base URL, timeout, or headers without changing global env:

```python
import os
from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.llm import LLMSettings
from replayt.persistence import JSONLStore

wf = Workflow("demo", version="1")  # define steps on wf ...

runner = Runner(
    wf,
    JSONLStore(Path(".replayt/runs")),
    log_mode=LogMode.redacted,
    llm_settings=LLMSettings(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.example.com/v1",
        model="anthropic/claude-sonnet-4.6",
        timeout_seconds=90.0,
        extra_headers={"X-My-Gateway": "team-b"},
    ),
)
```

**Per-call** - override one step without forking the library: `ctx.llm.with_settings(model=..., temperature=..., top_p=..., timeout_seconds=..., max_tokens=..., http_retries=..., provider=..., base_url=..., native_response_format=True, response_format={"type": "json_object"}, extra_headers={...}, extra_body={...}, experiment={...}, call_label=..., llm_tags=[...])`. The `response_format` dict is forwarded on `complete_text` (clear defaults with `with_settings(response_format={})`, or skip for one call via `complete_text(..., response_format=None)`). `http_retries` is the count of *extra* POST attempts after the first on retryable HTTP statuses (429, 500, 502, 503, 504), inheriting from `LLMSettings.http_retries` when unset on the bridge; cap is 25. You can also pass `complete_text(..., http_retries=...)` or `parse(..., http_retries=...)` for a single call. Overrides appear under `effective` on `llm_request` / `llm_response` events, including a compact `effective.response_format` when the gateway request used one (not the full embedded schema). The bridge also emits stable `messages_sha256` / `effective_sha256` fingerprints (plus `schema_sha256` and `schema_name` for `parse(...)`, and optional `schema_name` on `complete_text(..., schema_name=...)` when you label a freeform call) so exact prompt and schema revisions stay comparable in redacted logs. Optional `call_label` tags multiple LLM round trips inside the same handler (also top-level on matching LLM and structured-output lines). Optional `llm_tags` adds sorted-unique short strings on `effective` (and top-level on matching lines) for analytics; they are not sent on the HTTP body unless you add them to `extra_body` yourself. Use `experiment` for run-level cohort or dataset labels, not as a full eval product; see [`SCOPE.md`](SCOPE.md).

```python
decision = (
    ctx.llm.with_settings(
        provider="openai",
        base_url="https://gateway.example.com/v1",
        top_p=0.15,
        native_response_format=True,
        experiment={"prompt_hash": "9d2e"},
    )
    .parse(Decision, messages=[{"role": "user", "content": "Return strict JSON only."}])
)
```

If parsing still fails, replayt emits `structured_output_failed` with a stage such as `schema_limit`, `json_extract`, or `schema_validate` so the JSONL tells you whether the miss was an oversized embedded schema, malformed JSON, an oversized response, or a schema mismatch; when settings are known, the payload includes the same `effective` bag as successful parses (so `schema_limit` rows still show `model` and `experiment` even though no `llm_request` was written). For Pydantic rejections at `schema_validate`, the event also includes bounded `validation_issues` (field path and message) plus `validation_issue_count` when many fields fail at once. When parsing succeeds, `structured_output` also carries the resolved `effective` settings plus `usage`, `latency_ms`, and `finish_reason` from that completion (same fields as on the preceding `llm_response`, including optional `http_attempts` / `http_status` when the OpenAI-compat client recorded how many POST tries succeeded, and optional `http_response_request_id` / `http_response_processing_ms` / `http_response_cf_ray` when the gateway returned matching response headers) so you can sum tokens or latency per `schema_name`, spot rate-limit storms (`http_attempts` > 1), join vendor support tickets on `http_response_request_id`, or filter on `model` / `experiment`, with a single `jq` or SQL filter.

For timeouts, retries, or betas exposed only through the official `openai` SDK, keep replayt's graph and approvals as-is and call the SDK **inside a single step** (see **Pattern: OpenAI Python SDK inside a step** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md)).

## replayt in CI

Use **`--output json`** and shell on **exit status** (0 = completed, 1 = failed, 2 = paused / needs approval):

```bash
set -euo pipefail
export OPENAI_API_KEY="${OPENAI_API_KEY:?}"
OUT="$(replayt run mypkg.workflow:wf \
  --inputs-json "{\"id\":\"${GITHUB_RUN_ID}\"}" \
  --output json)"
echo "$OUT"
echo "$OUT" | jq -e '.status == "completed"' >/dev/null
```

For **no API key** in CI, tests should use **`MockLLMClient`** / **`run_with_mock`** (`from replayt.testing import MockLLMClient, run_with_mock`) or mock `httpx`; keep smoke workflows that hit a real provider optional. See **Pattern: golden path test (pytest)** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

Add **`replayt validate TARGET`** in CI to catch broken graphs without calling an LLM ([`CLI.md`](CLI.md)). For a quick graph + `--inputs-json` shape check without writing logs, use **`replayt run TARGET --dry-check`** (or **`replayt ci TARGET --dry-check`**).

When a pipeline needs the `run_id` or final status without scraping stdout, write the CI artifact directly:

```bash
replayt ci mypkg.workflow:wf \
  --inputs-json "{\"id\":\"${GITHUB_RUN_ID}\"}" \
  --summary-json .replayt/ci-summary.json

jq -r '.run_id, .status, .exit_code' .replayt/ci-summary.json
```

For shell wrappers that already rely on env vars, **`REPLAYT_SUMMARY_JSON=path/to/summary.json replayt run ...`** writes the same machine-readable payload.

To attach pipeline context without hard-coding vendor env var names into replayt, build a small JSON object and pass it as **`REPLAYT_CI_METADATA_JSON`** (only read when a summary path is in effect):

```bash
export REPLAYT_CI_METADATA_JSON="$(
  jq -n --arg url "${CI_PIPELINE_URL:-}" --arg sha "${CI_COMMIT_SHA:-}" \
    '{pipeline_url:$url, commit:$sha}'
)"
replayt ci mypkg.workflow:wf --summary-json .replayt/ci-summary.json
# jq '.ci_metadata' .replayt/ci-summary.json
```

For one-command preflight before the real job, **`replayt doctor --skip-connectivity --target TARGET --strict-graph`** now loads the workflow, validates its graph/input flags, and checks that the resolved log / SQLite destinations are usable without executing the run. If the shell also sets **`REPLAYT_JUNIT_XML`**, **`REPLAYT_SUMMARY_JSON`**, or **`REPLAYT_GITHUB_SUMMARY=1`**, the same doctor report now preflights those artifact sinks too, including a missing markdown sink when neither **`GITHUB_STEP_SUMMARY`** nor **`REPLAYT_STEP_SUMMARY`** is set.

### GitHub Actions and exit code `2`

`replayt run` / `replayt ci` exit **`2`** when the run pauses for approval. Treat that as **neutral** in Actions if approvals are expected, or fail the job if your CI run should never pause:

```yaml
- name: Run workflow
  run: replayt ci mypkg.workflow:wf --inputs-json '{"id":"${{ github.run_id }}"}'
  # exit 0 = completed, 1 = failed, 2 = paused (approval)

- name: Run workflow (fail if paused)
  run: replayt ci mypkg.workflow:wf --inputs-json '{"id":"${{ github.run_id }}"}'
  # Default: step fails on exit 1 or 2. Use a follow-up job or `continue-on-error` if you handle exit 2 elsewhere.
```
