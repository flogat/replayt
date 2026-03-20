# Examples

These examples show what replayt is good at in practice:

- concrete workflows
- explicit branching
- strict outputs
- local replay
- realistic approval gates

Install locally first:

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
# Optional: load from .env in your shell (replayt does not read .env by itself)
# set -a && source .env && set +a   # bash, if .env is export-safe
# direnv allow                        # if you use direnv + .envrc
```

See [`README.md`](../../README.md) for Windows activation lines, `replayt doctor`, optional extras (`[yaml]`), and LLM env vars (`OPENAI_BASE_URL`, `REPLAYT_MODEL`).

## 1. Hello world — `examples.e01_hello_world`

The smallest workflow in the tutorial set. It writes a greeting and a next action into context so you can inspect and replay the run.

Expected outcome: the run completes successfully and the final context includes `message="Hello, Sam! Your first replayt workflow ran."`, `next_action="Inspect this run, then replay it from the CLI."`, and `completed=true`, so you can compare a finished run against later, more complex examples.

```bash
replayt run examples.e01_hello_world:wf \
  --inputs-json '{"customer_name":"Sam"}'
```

Then inspect what happened:

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

## 2. Intake normalization — `examples.e02_intake_normalization`

Validate a raw lead payload, normalize formatting, and derive an internal segment.

Expected outcome: the run completes successfully and stores `normalized_lead` with `name="Sam Patel"`, `email="sam@example.com"`, `company="Northwind"`, a whitespace-normalized message, and `segment="enterprise"` because the sample message mentions a demo for many seats.

```bash
replayt run examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

## 3. Support routing — `examples.e03_support_routing`

A deterministic branching flow for support operations.

Expected outcome: the run completes successfully and writes `routing_decision` with `queue="billing"`, `priority="high"`, and `sla_hours=4` because the sample ticket mentions payment failure and the customer tier is `enterprise`.

```bash
replayt run examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

## 4. Typed tool calls — `examples.e04_tool_using_procurement`

Register strongly typed tools and use them from a workflow step.

Expected outcome: the run completes successfully, the event log shows typed calls to `calculate_total` and `budget_policy`, and the final `decision` records `total_cost=298.0`, `within_policy=true`, and `recommended_action="auto_approve"` for the sample Design request.

```bash
replayt run examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

## 5. Retries for flaky integrations — `examples.e05_retrying_vendor_lookup`

Show how a state can retry automatically before succeeding.

Expected outcome: the first `lookup` attempt fails with a temporary timeout, replayt retries automatically, the second attempt succeeds, and `lookup_summary` ends with `vendor_name="Acme Fulfillment"`, `status="active"`, `payment_terms="net-30"`, `risk_level="low"`, and `lookup_attempts=2`.

```bash
replayt run examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

## 6. Sales call prep brief — `examples.e06_sales_call_brief`

Use structured LLM output to turn CRM notes into a call brief.

Expected outcome: the run completes successfully and `call_brief` validates against the `CallBrief` schema, so `inspect` shows structured fields such as `customer_stage`, `top_goals`, `risks`, `recommended_talking_points`, and `next_step` instead of an unstructured paragraph.

```bash
replayt run examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

## 7. Customer feedback clustering — `examples.e07_feedback_clustering`

Use the LLM for batch summarization and prioritization.

Expected outcome: the run completes successfully and `feedback_summary` contains a schema-validated list of themes plus a `release_note_hint`; for the sample input you should expect themes around exports/performance and identity access (Okta SSO), each with priorities and suggested owners.

```bash
replayt run examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

## 8. Travel approval — `examples.e08_travel_approval`

Evaluate travel policy automatically, then pause for manager approval only when policy flags require it.

Expected outcome: with the sample input the run pauses with exit code 2 after `policy_check` stores `policy_flags=["high_cost", "late_notice"]` and requests `manager_review`; after approval it finishes with `travel_status="approved_for_booking"`, and after rejection it finishes with `travel_status="rejected"`.

```bash
replayt run examples.e08_travel_approval:wf \
  --inputs-json '{"trip":{"employee":"Sam Patel","destination":"New York","reason":"Customer onsite kickoff","estimated_cost":3200.0,"days_notice":5}}'
```

Approve it:

```bash
replayt resume examples.e08_travel_approval:wf <run_id> --approval manager_review
```

Reject it instead:

```bash
replayt resume examples.e08_travel_approval:wf <run_id> --approval manager_review --reject
```

## 9. Incident response — `examples.e09_incident_response`

Combine typed tools with an executive approval gate for sev1 communications.

Expected outcome: the sample incident is classified as `sev1` because `error_rate=12.5`, the run logs tool calls for paging and status-page draft creation, then pauses for `exec_comms`; approving resumes to `communication_plan="external_statuspage_and_internal_slack"`, while rejecting resumes to `communication_plan="internal_updates_only"`.

```bash
replayt run examples.e09_incident_response:wf \
  --inputs-json '{"incident":{"service":"api","error_rate":12.5,"customer_impact":"Checkout requests are failing for many customers.","suspected_cause":"Database connection pool exhaustion"}}'
```

For a sev1 incident, approve external comms:

```bash
replayt resume examples.e09_incident_response:wf <run_id> --approval exec_comms
```

Or keep the response internal-only:

```bash
replayt resume examples.e09_incident_response:wf <run_id> --approval exec_comms --reject
```

## 10. GitHub issue triage — `examples.issue_triage`

A relatable developer workflow with deterministic validation, LLM classification, and explicit routing.

Expected outcome: the sample issue passes validation, the LLM returns a `TriageDecision`, and the final context either contains a `response_template` asking for clarification or, more likely for this sample, a `routing` object with a category-backed queue, suggested label, and priority for engineering triage.

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

## 11. Refund policy workflow — `examples.refund_policy`

A constrained support decision flow where the output space stays narrow and auditable.

Expected outcome: the run completes successfully and `summary_for_agent` contains the schema-validated refund action, reason codes, and customer message; for the sample damaged-order ticket delivered 3 days ago, a refund-oriented outcome is plausible under the stated policy, but the exact action still comes from the model and remains auditable in the log.

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"My order arrived damaged and I need a refund.","order":{"order_id":"ORD-1001","amount_cents":12999,"delivered":true,"days_since_delivery":3}}'
```

## 12. Publishing preflight with approval gate — `examples.publishing_preflight`

Check draft copy, generate a structured checklist, and pause for a human publishing decision.

Expected outcome: the sample draft produces a checklist with one or more issues about unsupported or risky claims, then pauses for `publish` approval; approving resumes to `publish_status="approved"`, while rejecting resumes to `publish_status="aborted"`.

```bash
replayt run examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
```

Approve it:

```bash
replayt resume examples.publishing_preflight:wf <run_id> --approval publish
```

Reject it instead:

```bash
replayt resume examples.publishing_preflight:wf <run_id> --approval publish --reject
```

## Python file target

replayt can load a workflow directly from a Python file if it exports `wf` or `workflow`.

```bash
replayt run workflow.py --inputs-json '{"ticket":"hello"}'
```

## YAML workflow target

For small declarative flows, replayt can run a workflow directly from YAML.

```bash
replayt run workflow.yaml --inputs-json '{"route":"refund","ticket":"where is my order?"}'
```

## Graph export

```bash
replayt graph examples.e04_tool_using_procurement:wf
```

---

## Patterns (composition, not core features)

These are **not** shipped as frameworks inside replayt. They show how different teams stay within the design principles (explicit states, local logs, no hosted platform in core).

### Pattern: approval bridge (local UI)

**Scenario:** You want a web UI or Slack button instead of only `replayt resume`.

**Approach:**

1. Run the workflow until it pauses; note `run_id` and `approval_id` from `replayt inspect` / `approval_requested` events.
2. Your small service reads the JSONL file for that `run_id` (read-only is enough for display).
3. When a human approves, append the same `approval_resolved` event replayt expects (same schema as [`docs/RUN_LOG_SCHEMA.md`](../../docs/RUN_LOG_SCHEMA.md)), or shell out to `replayt resume TARGET RUN_ID --approval ID`.
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
TARGET = "examples.publishing_preflight:wf"  # your MODULE:wf or path


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

For a **shareable HTML timeline** without a server, run `replayt replay RUN_ID --format html --out run.html` (self-contained page using Tailwind CDN). For a richer dashboard, render HTML with Tailwind per [`documentation/STYLE.md`](../../documentation/STYLE.md).

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

Use your orchestrator for **retries between rows**, concurrency, and backpressure—not replayt.

### Pattern: OpenAI Python SDK inside a step

**Scenario:** You want `openai` package features (custom retries, streaming, vision, assistants betas) without waiting for replayt to wrap everything.

**Approach:** Inside a `@wf.step`, call the SDK directly, then **validate** with Pydantic and `ctx.set(...)`. Keep **transitions and approvals** in replayt; keep **provider SDK** in imperative Python inside the step. Only **after** validation should your handler `return "next_state"` so control flow stays explicit.

#### Sub-pattern: strict JSON exit shape (`response_format`)

Use the official client’s `response_format={"type": "json_object"}` (or newer JSON-schema modes) when available; map the assistant string into **one** Pydantic model before transitioning.

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
        model="gpt-4o-mini",
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

Build multimodal `messages`; still normalize to a **single** structured object you store on the context. LLM traffic from the SDK is **not** auto-logged by replayt—treat validated `ctx.set` outputs as your audit surface, or log a short summary yourself if policy requires it.

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

Stream for UX inside the step; accumulate text; then derive **one** structured summary (second API call with `ctx.llm.parse`, or strict JSON parse of the final buffer). replayt’s timeline should show **decisions**, not per-token deltas (see also **Pattern: stream inside step, log structured summary** below).

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
        model="gpt-4o-mini",
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

**Scenario:** You need a corporate HTTP proxy, custom signing, or a gateway SDK—more than `OPENAI_BASE_URL` and `extra_headers`—but you still want explicit replayt states.

**Approach:** Keep **`Runner(..., llm_settings=LLMSettings(...))`** for anything the built-in client supports (base URL, timeout, headers). For arbitrary stacks, call your wrapper **inside one `@wf.step`**, validate the result with **Pydantic**, `ctx.set(...)`, and return the next state explicitly. Do not hide transitions inside the wrapper.

### Pattern: golden path test (pytest)

**Scenario:** You want regression tests and “eval-like” checks without a built-in `replayt eval` command.

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
# then: replayt run … or Runner.run(...)
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

### Pattern: reusable workflow package

**Scenario:** Many services should import the same workflow without a “plugin registry.”

**Approach:** Publish an internal package (e.g. `my_org_replayt`) that defines `wf: Workflow` in a module. Consumers run `replayt run my_org_replayt.support:wf ...` after `pip install my-org-replayt==1.3.0`. No dynamic `importlib` loaders—just normal dependency pinning.

### Pattern: stream inside step, log structured summary

**Scenario:** Stakeholders want token streaming UX, but you do not want streaming as first-class log events.

**Approach:** If your provider SDK supports streaming, consume chunks **inside the step** (list comprehension, accumulator string). When the stream completes, **`ctx.llm.parse`** a **summary or structured object** from the final text—or derive it without another round-trip—and store only that. Timeline replay shows the validated outcome, not every delta.

### Pattern: OpenAI-compatible presets vs native provider SDKs

**Scenario:** You run Ollama, Groq, OpenRouter, or a corporate gateway. You want sensible defaults without hunting for base URLs.

**Approach:** In Python, `LLMSettings.for_provider("ollama")` (also: `openai`, `groq`, `together`, `openrouter`, `anthropic`). In the shell, set `REPLAYT_PROVIDER` — `OPENAI_BASE_URL` and `REPLAYT_MODEL` still **override** the preset defaults when set. Native **Anthropic** HTTP APIs are not OpenAI-`/chat/completions`-compatible; point `OPENAI_BASE_URL` at an **OpenAI-compatible proxy** (LiteLLM, corporate gateway) or call `anthropic`’s SDK **inside one step** and validate with Pydantic:

```python
# Inside a @wf.step — illustrative; pip install anthropic
# import anthropic
# client = anthropic.Anthropic()
# msg = client.messages.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[...])
# text = "".join(b.text for b in msg.content if getattr(b, "text", None))
# ctx.set("claude_reply", MyModel.model_validate_json(text).model_dump())
```

### Pattern: custom EventStore for external sinks

**Scenario:** You forward copies of run events to Datadog, an OTEL collector, or an HTTP log intake **without** making replayt a hosted observability product.

**Approach:** Implement the `EventStore` protocol: wrap **`JSONLStore`** so every `append` writes locally first, then asynchronously or best-effort POSTs a copy. Keep JSONL canonical on disk; treat the remote sink as optional.

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

**Approach:** Implement `EventStore` yourself (or wrap `JSONLStore`) so each **logical** replayt event is serialized to JSON, encrypted with **Fernet** (`pip install cryptography`), then written as one wrapped record per line (below uses a small envelope dict). Load the key from your KMS or an env var **outside** replayt core.

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

`inspect` / `replay` then see **decrypted** events only if you use this store for both writes and reads; standard CLI on raw files expects normal replayt event JSON—**document** that operators must use your decrypting tooling or a small bridge script.

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

**Scenario:** Multiple workflows share a validation phase; you do not want a hidden “meta-planner.”

**Approach:** From a parent step, call **`Runner.run`** on a **child** `Workflow` with a **deterministic** child `run_id` (for example ``f"{parent_run_id}__validate"``). Inspect the child’s JSONL or `RunResult` in Python, then **return an explicit next state** on the parent. Never let the child model choose the parent transition string without your code mapping it.

```python
import uuid
from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

parent = Workflow("parent", version="1")
child = Workflow("child_validate", version="1")
# … define child wf …

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

**Approach:** Keep **old handlers** reachable when replaying legacy runs (gate on stored `workflow_version` from `run_started` if you snapshot it in context), or write a **one-off migration script** that reads JSONL, maps old `structured_output` payloads to new shapes, and writes new artifacts—**do not** silently auto-mutate production logs. Prefer **new runs** on the new graph with explicit inputs at organizational boundaries.

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
</think>
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
TodoWrite
