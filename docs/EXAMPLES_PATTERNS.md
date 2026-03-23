# Examples: composition patterns

These recipes are **not** built into replayt core. Use them to wire up queues, UIs, other SDKs, and analytics around explicit states and local logs.

**Tutorial first:** work through sections 1-14 in [`src/replayt_examples/README.md`](../src/replayt_examples/README.md) in order. Return here when you need a reference pattern.

---

## Patterns (composition, not core features)

These are patterns you implement yourself, not features shipped inside replayt.

### Pattern: approval bridge (local UI)

**Scenario:** You want a web UI or Slack button instead of only `replayt resume`.

**Approach:**

1. Run the workflow until it pauses; note `run_id` and `approval_id` from `replayt inspect` / `approval_requested` events.
2. Your small service reads the JSONL file for that `run_id` (read-only is enough for display).
3. When a human approves, append the same `approval_resolved` event replayt expects (same schema as [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md)), or shell out to `replayt resume TARGET RUN_ID --approval ID`.
4. Call `replayt run ... --resume --run-id ...` or use `Runner.run(..., resume=True)` in Python.

replayt remains the **engine**; your app owns auth, routing, and UX.

**Minimal API sketch:** an HTTP server can expose `GET /runs/{run_id}` that streams the JSONL for that run (parse NDJSON lines into a list for the UI). `POST /runs/{run_id}/approvals/{approval_id}` validates the user, then either runs `subprocess.run(["replayt", "resume", target, run_id, "--approval", approval_id], check=True)` or appends one `approval_resolved` line matching the schema your replayt version expects.

**FastAPI-shaped reference** (install `fastapi` + `uvicorn` in *your* project; add **auth** before production):

```python
# Illustrative only: JSON API + shelling out to replayt resume.
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI()
LOG_DIR = Path(".replayt/runs")
TARGET = "replayt_examples.publishing_preflight:wf"  # your MODULE:wf or path


@app.get("/api/runs/{run_id}/events")
def list_events(run_id: str) -> list[dict]:
    path = LOG_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        raise HTTPException(404, "unknown run")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@app.post("/api/runs/{run_id}/approvals/{approval_id}")
def resolve(run_id: str, approval_id: str, reject: bool = False) -> dict:
    cmd = ["replayt", "resume", TARGET, run_id, "--approval", approval_id, "--log-dir", str(LOG_DIR)]
    if reject:
        cmd.append("--reject")
    subprocess.run(cmd, check=True)
    return {"ok": True}
```

For a **shareable HTML timeline** without a server, run `replayt replay RUN_ID --format html --out run.html` (self-contained page using Tailwind CDN). For a summary report, use `replayt report RUN_ID --out report.html`. For Tailwind conventions when building your own UI, see [`docs/STYLE.md`](STYLE.md).

### Pattern: batch driver (Airflow / Celery / plain loop)

**Scenario:** Thousands of rows, each should become one replayt run with full audit history.

**Approach:**

```python
from pathlib import Path
from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore
import uuid

# wf: your Workflow

def run_batch(rows: list[dict], log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(rows):
        run_id = str(uuid.uuid4())
        store = JSONLStore(log_root)  # or one store, unique run_ids
        runner = Runner(wf, store, log_mode=LogMode.redacted)
        result = runner.run(inputs={"row": row, "index": i}, run_id=run_id)
        assert result.status in {"completed", "failed", "paused"}
```

Handle **retries between rows**, concurrency, and backpressure in your orchestrator. replayt runs one job at a time inside its process.

### Pattern: promotion / environment metadata

**Scenario:** You need every archived JSONL line to show whether a run came from dev, staging, or production without baking environment names into workflow code.

**Approach:** Pass promotion labels as **`run_metadata`** so they land on `run_started` and stay filterable with **`replayt runs --run-meta`**. From CI, export stable JSON (often from your deploy system's env vars) into **`--metadata-json`**:

```bash
replayt ci "$TARGET" --metadata-json "{\"deployment_tier\":\"prod\",\"change_ticket\":\"CHG-12345\"}"
```

In Python, the same shape is `Runner.run(..., run_metadata={"deployment_tier": "prod", "change_ticket": "CHG-12345"})`. Keep secrets out of metadata; use ticket ids and deployment labels instead of raw tokens.

### Pattern: workflow contract allowlist in policy hooks

**Scenario:** Compliance wants only CI-approved workflow digests to run or resume in production, without replayt hosting RBAC or reading your IdP.

**Approach:** Pin contracts with **`replayt contract TARGET --check path/to/workflow.contract.json`** in CI. At runtime, read **`REPLAYT_WORKFLOW_CONTRACT_SHA256`** (and optional name/version) inside **`run_hook`** / **`resume_hook`** and compare to your allowlist file or CMDB query; exit non-zero to block before new JSONL events. The same three env vars are also injected into **`export_hook`**, **`seal_hook`**, and **`verify_seal_hook`** (parsed from **`run_started`**; **`export_hook`** also receives **`REPLAYT_TARGET`** when you pass **`--target`** on export) so archival and verify steps can reuse one allowlist script. When **`run_started`** recorded **`run_metadata`**, **`tags`**, or **`experiment`**, those hooks also receive **`REPLAYT_RUN_METADATA_JSON`**, **`REPLAYT_RUN_TAGS_JSON`**, and **`REPLAYT_RUN_EXPERIMENT_JSON`** (same strings as **`run_hook`**) so tier or ticket policy can run without **`jq`**. To detect drift against the original run, parse the first **`run_started`** line in the run's JSONL and compare its **`runtime.workflow.contract_sha256`** to the hook env (or to your allowlist).

```bash
# CI: fail when the live workflow drifts from the checked-in contract snapshot
replayt contract "$TARGET" --check policies/workflow.contract.json
```

**Hook env: logging contract.** Every trusted policy subprocess (`run_hook`, `resume_hook`, `export_hook`, `seal_hook`, `verify_seal_hook`) receives **`REPLAYT_LOG_MODE`**, **`REPLAYT_FORBID_LOG_MODE_FULL`** (`1` / `0`), **`REPLAYT_REDACT_KEYS_JSON`** (sorted JSON array of field names from project config / CLI, never secret values), and **`REPLAYT_REPLAYT_VERSION`** (installed **replayt** version string, same as `replayt.__version__`). Use the logging fields when auditors want proof that `log_mode=full` is blocked or that specific structured keys are redacted before you allow resume, export, or seal; compare **`REPLAYT_REPLAYT_VERSION`** to a pinned allowlist when production gates must reject stale CLIs. The canonical sorted env name list is also in **`replayt version --format json`** → **`policy_hook_env_catalog`**.

**Beyond core: stronger digests and control frameworks.** If policy requires FIPS-approved primitives, PKCS#7, or HSM-backed signing, run **`openssl dgst`** / **`openssl cms`** (or your org tool) in **`seal_hook`** / **`export_hook`** on the tarball or manifest path replayt already wrote—do not fork core for module-validation semantics. If auditors want SOC 2 / ISO control ids on each event, add a **`ctx.note`** from application code or append a small sidecar in **your** CI job; replayt keeps JSONL schema stable and avoids embedding vendor-specific control taxonomies in core.

### Pattern: OpenAI Python SDK inside a step

**Scenario:** You want `openai` package features (custom retries, streaming, vision, assistants betas) without waiting for replayt to wrap everything.

**Approach:** Inside a `@wf.step`, call the SDK directly, then **validate** with Pydantic and `ctx.set(...)`. Keep **transitions and approvals** in replayt; keep **provider SDK** in imperative Python inside the step. Only **after** validation should your handler `return "next_state"` so control flow stays explicit.

#### Sub-pattern: strict JSON exit shape (`response_format`)

Use the official client's `response_format={"type": "json_object"}` (or newer JSON-schema modes) when available; map the assistant string into **one** Pydantic model before transitioning.

```python
from openai import OpenAI
from pydantic import BaseModel

class Plan(BaseModel):
    next_action: str
    risk_notes: str

@wf.step("plan_with_sdk")
def plan_with_sdk(ctx):
    client = OpenAI()
    r = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": "Return JSON only: next_action and risk_notes."}],
    )
    text = r.choices[0].message.content or "{}"
    plan = Plan.model_validate_json(text)
    ctx.set("plan", plan.model_dump())
    return "execute"
```

#### Sub-pattern: vision / multimodal input

Build multimodal `messages`; still normalize to a **single** structured object you store on the context. LLM traffic from the SDK is **not** auto-logged by replayt. Treat validated `ctx.set` outputs as your audit surface, or log a short summary yourself if policy requires it.

```python
from openai import OpenAI

@wf.step("screen_review")
def screen_review(ctx):
    client = OpenAI()
    r = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List UI defects you see."},
                    {"type": "image_url", "image_url": {"url": "https://example.com/screenshot.png"}},
                ],
            }
        ],
    )
    ctx.set("screen_review_text", r.choices[0].message.content or "")
    return "triage"
```

#### Sub-pattern: streaming + structured summary

Stream for UX inside the step; accumulate text; then derive **one** structured summary (second API call with `ctx.llm.parse`, or strict JSON parse of the final buffer). replayt's timeline should show **decisions**, not per-token deltas (see also **Pattern: stream inside step, log structured summary** below).

```python
from openai import OpenAI
from pydantic import BaseModel

class StreamSummary(BaseModel):
    headline: str
    confidence: float

@wf.step("stream_then_struct")
def stream_then_struct(ctx):
    client = OpenAI()
    stream = client.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        stream=True,
        messages=[{"role": "user", "content": "Long explanation of the bug."}],
    )
    parts: list[str] = []
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)
    final_text = "".join(parts)
    ctx.set("raw_stream_text", final_text[:50_000])  # optional cap
    summary = ctx.llm.parse(
        StreamSummary,
        messages=[{"role": "user", "content": f"Summarize in JSON: {final_text[:8000]}"}],
    )
    ctx.set("stream_summary", summary.model_dump())
    return "done"
```

### Pattern: stronger log redaction

**Scenario:** You need structured outputs in logs but want to avoid even short LLM body previews.

**Approach:** Run the CLI with `--log-mode structured_only` (or `LogMode.structured_only` in `Runner`). LLM bodies are not stored; validated `structured_output` events still capture schema-shaped results for audit.

### Pattern: wrap your own HTTP / gateway client

**Scenario:** You need a corporate HTTP proxy, custom signing, or a gateway SDK beyond what `OPENAI_BASE_URL` and `extra_headers` cover, and you still want explicit replayt states.

**Approach:** Keep **`Runner(..., llm_settings=LLMSettings(...))`** for anything the built-in client supports (base URL, timeout, headers). For arbitrary stacks, call your wrapper **inside one `@wf.step`**, validate the result with **Pydantic**, `ctx.set(...)`, and return the next state explicitly. Do not hide transitions inside the wrapper.

### Pattern: golden path test (pytest)

**Scenario:** You want regression tests and "eval-like" checks without a built-in `replayt eval` command.

**Approach:** Call **`Runner.run`** from pytest with **fixed inputs**. Prefer **mocking** `httpx` or, for graph-level tests without touching transports, use **`MockLLMClient`** with **`run_with_mock`** and **`assert_events`** (`from replayt.testing import ...` or `from replayt import MockLLMClient, run_with_mock`). Assert on `result.status`, final context keys, or `structured_output` events in JSONL. For human-readable debugging after a failed CI run, point people at **`replayt replay RUN_ID`** with a saved log directory.

### Pattern: pre-run secret check

**Scenario:** You want fast, explicit failure when `OPENAI_API_KEY` is missing instead of a deep stack trace mid-run.

**Approach:**

```python
import os
import sys

def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"missing env {name}", file=sys.stderr)
        sys.exit(2)
    return v

require_env("OPENAI_API_KEY")
# then: replayt run ... or Runner.run(...)
```

### Pattern: DuckDB ad-hoc analytics

**Scenario:** You want SQL over many runs without shipping logs to a warehouse from core replayt.

**Approach:** `JSONLStore` writes **one file per run** (`{run_id}.jsonl`). Point DuckDB at the directory (adjust the path):

```sql
SELECT "type" AS typ, COUNT(*)
FROM read_json_auto('.replayt/runs/*.jsonl', format='newline_delimited')
GROUP BY 1
ORDER BY 2 DESC;
```

Treat this as **your** analytics layer; replayt keeps writing append-only JSONL.

### Pattern: queue worker

**Scenario:** A broker (Redis, SQS, RabbitMQ) hands you jobs; each job should be exactly one replayt run.

**Approach:** Pseudocode:

```python
import uuid
from pathlib import Path

from replayt import LogMode, Runner
from replayt.persistence import JSONLStore

# wf, receive, ack = your queue bindings

def handle_message(payload: dict) -> None:
    run_id = str(uuid.uuid4())
    store = JSONLStore(Path(".replayt/runs"))
    runner = Runner(wf, store, log_mode=LogMode.redacted)
    result = runner.run(inputs=payload, run_id=run_id)
    if result.status not in {"completed", "paused", "failed"}:
        raise RuntimeError(result)
# on success: ack(message)
```

Use the broker for **retries and DLQ**, not implicit replays inside replayt.

### Pattern: framework in a sandbox step

**Scenario:** LangChain / LlamaIndex / similar is already mandated in your org.

**Approach:** Call **`chain.invoke(...)`** (or equivalent) **inside a single step**. Map the framework output to **one Pydantic model**, `ctx.set("step_result", model.model_dump())`, then **`return "next_state"`** so branching stays visible in replayt. Never let the framework decide the FSM transition without your Python code expressing it.

Use **`ctx.note(...)`** for explicit sub-run breadcrumbs, then narrow a run with **`replayt inspect RUN_ID --event-type step_note`** (repeat the flag for OR) when you want framework-shaped signals without `jq`. For **`tool_call`** lines, use **`replayt inspect RUN_ID --tool TOOL_NAME`** (same OR rules as **`replayt runs --tool`**) or **`--event-type tool_call`** when you need every invocation. To find local runs that validated a particular Pydantic **`schema_name`**, list with **`replayt runs --structured-schema MyModel`** (repeat for OR); **`replayt stats`** and **`replayt inspect RUN_ID --structured-schema MyModel`** accept the same match rules. When you route **`ctx.llm.with_settings(model=...)`** or gateway aliases across steps, list runs that actually hit a provider id with **`replayt runs --llm-model gpt-4o-mini`** (repeat for OR); **`replayt stats`** and **`replayt inspect RUN_ID --llm-model …`** match on logged **`effective.model`** (legacy logs fall back to top-level **`model`** on the same event types). **`replayt report RUN_ID --llm-model …`**, **`replayt diff RUN_A RUN_B --llm-model …`**, and **`replayt report-diff … --llm-model …`** apply the same slice to structured outputs and token-style summaries (diff keeps full-run states and tool-call counts). When a sandboxed graph hits token limits, **`llm_response`** events record the provider **`finish_reason`**; use **`replayt runs --finish-reason length`** or **`replayt inspect RUN_ID --finish-reason length`** to triage those runs without ad-hoc **`jq`**.

### Pattern: reusable workflow package

**Scenario:** Many services should import the same workflow without a "plugin registry."

**Approach:** Publish an internal package (e.g. `my_org_replayt`) that defines `wf: Workflow` in a module. Consumers run `replayt run my_org_replayt.support:wf ...` after `pip install my-org-replayt==1.3.0`. Skip dynamic `importlib` loaders; pin versions like any other dependency.

When you want **`Workflow.version`** to track the **same string as the installed wheel**, set it explicitly from metadata (still one line in *your* code, not magic inside replayt):

```python
from importlib.metadata import version as dist_version
from replayt.workflow import Workflow

wf = Workflow("support", version=dist_version("my_org_replayt"))
```

### Pattern: stream inside step, log structured summary

**Scenario:** Stakeholders want token streaming UX, but you do not want streaming as first-class log events.

**Approach:** If your provider SDK supports streaming, consume chunks **inside the step** (list comprehension, accumulator string). When the stream completes, **`ctx.llm.parse`** a **summary or structured object** from the final text, or derive it without another round-trip, and store only that. Timeline replay shows the validated outcome, not every delta.

### Pattern: OpenAI-compatible presets vs native provider SDKs

**Scenario:** You run Ollama, Groq, OpenRouter, or a corporate gateway. You want sensible defaults without hunting for base URLs.

**Approach:** In Python, `LLMSettings.for_provider("ollama")` (also: `openai`, `groq`, `together`, `openrouter`, `anthropic`). In the shell, set `REPLAYT_PROVIDER`; `OPENAI_BASE_URL` and `REPLAYT_MODEL` still **override** the preset defaults when set. Native **Anthropic** HTTP APIs are not OpenAI-`/chat/completions`-compatible; point `OPENAI_BASE_URL` at an **OpenAI-compatible proxy** (LiteLLM, corporate gateway) or call `anthropic`'s SDK **inside one step** and validate with Pydantic:

```python
# Inside a @wf.step (illustrative; pip install anthropic)
# import anthropic
# client = anthropic.Anthropic()
# msg = client.messages.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[...])
# text = "".join(b.text for b in msg.content if getattr(b, "text", None))
# ctx.set("claude_reply", MyModel.model_validate_json(text).model_dump())
```

### Pattern: custom EventStore for external sinks

**Scenario:** You forward copies of run events to Datadog, an OTEL collector, or an HTTP log intake **without** making replayt a hosted observability product.

**Approach:** Write an `EventStore` wrapper: wrap **`JSONLStore`** so every `append` writes locally first, then asynchronously or best-effort POSTs a copy. Keep JSONL canonical on disk; treat the remote sink as optional.

```python
from __future__ import annotations

import json
from typing import Any

import httpx

from replayt.persistence.base import EventStore
from replayt.persistence.jsonl import JSONLStore

class ForwardingStore:
    def __init__(self, inner: JSONLStore, sink_url: str, headers: dict[str, str] | None = None) -> None:
        self._inner = inner
        self._sink_url = sink_url.rstrip("/")
        self._headers = headers or {}

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        self._inner.append(run_id, event)
        try:
            with httpx.Client(timeout=3.0) as client:
                client.post(
                    self._sink_url,
                    headers={"Content-Type": "application/json", **self._headers},
                    content=json.dumps({"run_id": run_id, "event": event}, default=str).encode(),
                )
        except Exception:
            pass  # your policy: log, dead-letter queue, etc.

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        return self._inner.load_events(run_id)

# runner = Runner(wf, ForwardingStore(JSONLStore(Path(".replayt/runs")), "https://ingest.example/v1/replayt"))
```

### Pattern: encrypted run logs

**Scenario:** Compliance wants encryption at rest on the JSONL directory.

**Approach:** Write your own `EventStore` (or wrap `JSONLStore`) so each **logical** replayt event is serialized to JSON, encrypted with **Fernet** (`pip install cryptography`), then written as one wrapped record per line (below uses a small envelope dict). Load the key from your KMS or an env var **outside** replayt core.

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from replayt.persistence.jsonl import JSONLStore

class FernetWrappedJSONLStore:
    # Each line on disk is JSON {"c": "<fernet ciphertext>"} for one replayt event blob.

    def __init__(self, inner: JSONLStore, key: bytes) -> None:
        self._inner = inner
        self._fernet = Fernet(key)

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        blob = self._fernet.encrypt(json.dumps(event, default=str).encode("utf-8"))
        self._inner.append(run_id, {"c": blob.decode("ascii")})

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self._inner.load_events(run_id):
            token = row.get("c")
            if not isinstance(token, str):
                continue
            raw = self._fernet.decrypt(token.encode("ascii"))
            out.append(json.loads(raw.decode("utf-8")))
        return out
```

`inspect` / `replay` then see **decrypted** events only if you use this store for both writes and reads. The stock CLI on raw files expects normal replayt event JSON, so **document** that operators must use your decrypting tooling or a small bridge script.

### Pattern: post-hoc PII scrub on JSONL files

**Scenario:** You must redact emails or account IDs from older runs.

**Approach:** Offline script: read each `{run_id}.jsonl`, `json.loads` per line, walk dicts/lists and replace keys like `email` or regex-substitute string fields, then rewrite the file (or write to a new directory). Keep backups; this is **your** data-pipeline step, not a core command.

```python
import json
import re
from pathlib import Path

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scrub_obj(o):  # noqa: ANN001
    if isinstance(o, dict):
        return {k: scrub_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub_obj(v) for v in o]
    if isinstance(o, str):
        return EMAIL.sub("<redacted-email>", o)
    return o


def scrub_file(path: Path) -> None:
    lines = [scrub_obj(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.write_text("\n".join(json.dumps(x, default=str) for x in lines) + "\n", encoding="utf-8")
```

### Pattern: workflow composition via explicit sub-run

**Scenario:** Multiple workflows share a validation phase; you do not want a hidden "meta-planner."

**Approach:** From a parent step, call **`Runner.run`** on a **child** `Workflow` with a **deterministic** child `run_id` (for example ``f"{parent_run_id}__validate"``). Inspect the child's JSONL or `RunResult` in Python, then **return an explicit next state** on the parent. Never let the child model choose the parent transition string without your code mapping it.

```python
import uuid
from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

parent = Workflow("parent", version="1")
child = Workflow("child_validate", version="1")
# ... define child wf ...

@parent.step("start")
def start(ctx):
    pid = str(uuid.uuid4())
    ctx.set("parent_run_marker", pid)
    sub_id = f"{pid}__validate"
    sub_store = JSONLStore(Path(".replayt/runs"))
    sub_result = Runner(child, sub_store, log_mode=LogMode.redacted).run(
        inputs={"ticket": ctx.get("ticket")}, run_id=sub_id
    )
    ctx.set("validate_status", sub_result.status)
    if sub_result.status != "completed":
        return "escalate"
    return "proceed"
```

### Pattern: workflow version migration

**Scenario:** You shipped `Workflow("support", version="1")` and need `version="2"` without losing old JSONL.

**Approach:** Keep **old handlers** reachable when replaying legacy runs (gate on stored `workflow_version` from `run_started` if you snapshot it in context), or write a **one-off migration script** that reads JSONL, maps old `structured_output` payloads to new shapes, and writes new artifacts. **Do not** silently auto-mutate production logs. Prefer **new runs** on the new graph with explicit inputs at organizational boundaries.

```python
# Sketch: branch inside a step based on a context flag set from inputs.
@wf.step("normalize")
def normalize(ctx):
    ver = ctx.get("policy_version", wf.version)
    if ver == "1":
        ctx.set("ticket", legacy_ticket_shape(ctx.get("raw")))
    else:
        ctx.set("ticket", modern_ticket_shape(ctx.get("raw")))
    return "classify"
```

---

## Workaround patterns (rejected features: composition, not core)

Common requests we keep out of core. Implement these in your own stack; they are patterns, not shipped features.

### Pattern: async runner (use `asyncio.to_thread`)

**Request:** "I need `await runner.run_async(...)` for my FastAPI app."

**Why rejected:** Doubles the public API surface; cascading complexity through async EventStore, async tool calls, and async step handlers.

**Workaround:** Use `asyncio.to_thread` (Python 3.9+) to run the synchronous `Runner.run` in a thread pool:

```python
import asyncio
from replayt import Runner

# runner: Runner (configured as usual)

async def run_workflow(payload: dict, run_id: str) -> dict:
    result = await asyncio.to_thread(runner.run, inputs=payload, run_id=run_id)
    return {"run_id": result.run_id, "status": result.status}
```

The run is still deterministic and logged; the async boundary is yours.

### Pattern: webhook / lifecycle callbacks

**Request:** "I want Slack notifications when a run completes or fails."

**Why rejected:** Webhook config, auth, retry logic, and failure semantics are a product surface, not a runtime primitive. Conflicts with local-first.

**Workaround:** Wrap `Runner.run` in your notification layer:

```python
import httpx
from replayt import Runner

def run_with_notify(runner: Runner, wf_inputs: dict, notify_url: str) -> dict:
    result = runner.run(inputs=wf_inputs)
    httpx.post(notify_url, json={"run_id": result.run_id, "status": result.status})
    return {"run_id": result.run_id, "status": result.status}
```

Or use the `ForwardingStore` pattern (above) to stream events in real-time to any HTTP sink. The notification layer is yours; replayt stays the engine.

For **shell / CI** wrappers, treat **`replayt run`** / **`replayt ci`** exit code **`2`** as paused (approval or similar), then notify with the `run_id` from stdout or from your **`--summary-json`** artifact. To list paused backlog across logs, use **`replayt runs --status paused --log-dir ...`** (combine with **`--run-meta`** / **`--experiment`** when you tag runs for a tenant or experiment). When a framework-heavy step logs several **`ctx.tools.call`** invocations, **`replayt runs --tool TOOL_NAME`** finds recent runs that exercised a specific tool without hand-grepping JSONL.

**In-process policy / trace IDs:** For lightweight hooks without a second workflow engine, pass **`before_step`** / **`after_step`** to **`Runner(...)`** in Python (`before_step` runs after context schema checks, before the handler; **`after_step`** runs after a successful return, before `state_exited`). Keep side effects explicit; do not move control flow out of step handlers.

### Pattern: dashboard without a dashboard (use existing tools)

**Request:** "I want a web app to browse runs, view timelines, and approve pending runs from the browser."

**Why rejected:** Auth, sessions, deployment, and live updates are a separate product. Core stays local-first; replayt stays the engine.

**Workaround:** Stitch together tools you already use:

1. **Single-run HTML report:** `replayt report RUN_ID --out run.html` produces a self-contained shareable page.
2. **SQL over runs with datasette:** Point [datasette](https://datasette.io/) at your SQLite store for an instant browsable, filterable UI:

```bash
pip install datasette
replayt run my_workflow.py --sqlite .replayt/runs.db --inputs-json '...'
datasette .replayt/runs.db
```

3. **DuckDB ad-hoc analytics:** Query JSONL logs directly (see DuckDB pattern above).
4. **Approval bridge:** See the FastAPI approval bridge pattern above for a minimal custom approval API.

Choose the pieces that fit your setup.

### Pattern: static graph with dynamic data (no runtime state creation)

**Request:** "I want the LLM to invent new states at runtime -- 'I need a research step, then a synthesis step.' The graph should grow dynamically."

**Why rejected:** Directly violates *determinism over autonomy* and *explicit states over hidden loops*. If the model can create states, the workflow is no longer inspectable before execution, and replay semantics break.

**Workaround:** Pre-declare all possible states. Let the LLM populate *data* (what to do), not *graph structure* (which states exist):

```python
from pydantic import BaseModel

class Plan(BaseModel):
    steps: list[str]
    reasoning: str

@wf.step("plan")
def plan(ctx):
    plan = ctx.llm.parse(Plan, messages=[
        {"role": "user", "content": f"Plan tasks for: {ctx.get('goal')}"}
    ])
    ctx.set("plan", plan.model_dump())
    ctx.set("step_index", 0)
    return "execute"

@wf.step("execute")
def execute(ctx):
    plan = ctx.get("plan", {})
    idx = ctx.get("step_index", 0)
    steps = plan.get("steps", [])
    if idx >= len(steps):
        return "summarize"
    task = steps[idx]
    result = ctx.llm.complete_text(messages=[
        {"role": "user", "content": f"Execute this task: {task}"}
    ])
    ctx.set(f"result_{idx}", result)
    ctx.set("step_index", idx + 1)
    return "execute"  # loop back

@wf.step("summarize")
def summarize(ctx):
    ctx.set("status", "all_tasks_complete")
    return None
```

For variable-length plans, use a loop state with a counter. The graph is `plan -> execute -> (loop) -> summarize` -- three states, fully inspectable, replayable.

### Pattern: parallel I/O inside one step (no concurrent FSM steps)

**Request:** "My workflow has `enrich_from_crm` and `enrich_from_billing` -- two independent API calls. Running them sequentially doubles latency. I want parallel steps."

**Why rejected:** Parallel execution within a single run introduces concurrency semantics (shared mutable context, race conditions, non-deterministic event ordering) that break determinism and make replay ambiguous.

**Workaround:** Use `concurrent.futures` inside one step. The step handler is the concurrency boundary; the runner sees a single atomic state transition:

```python
import concurrent.futures

def fetch_crm(account_id: str) -> dict:
    # your CRM API call
    ...

def fetch_billing(account_id: str) -> dict:
    # your billing API call
    ...

@wf.step("enrich")
def enrich(ctx):
    account_id = ctx.get("account_id")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        crm_future = pool.submit(fetch_crm, account_id)
        billing_future = pool.submit(fetch_billing, account_id)
        ctx.set("crm_data", crm_future.result(timeout=30))
        ctx.set("billing_data", billing_future.result(timeout=30))
    return "score"
```

Parallelism lives *inside* one step, not across the FSM. For truly independent enrichment workflows, run them as separate `Runner.run()` calls (separate run IDs, separate logs) and merge results in a parent step.
