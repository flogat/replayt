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

The smallest workflow in the tutorial set. It writes a greeting and a next action into context so you can inspect and replay the run. Expect a short successful run whose final context includes a greeting for the customer and a simple `next_action` value, which makes it useful for learning what `inspect` and `replay` output look like on a minimal workflow.

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

Validate a raw lead payload, normalize formatting, and derive an internal segment. Expect the output context to contain trimmed and normalized lead fields plus a deterministic segment such as SMB or enterprise, showing how replayt turns messy inputs into auditable structured state.

```bash
replayt run examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

## 3. Support routing — `examples.e03_support_routing`

A deterministic branching flow for support operations. Expect the run to choose a route based on ticket details and customer tier, so the final state makes it obvious whether the ticket was escalated, prioritized, or sent through a standard support path.

```bash
replayt run examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

## 4. Typed tool calls — `examples.e04_tool_using_procurement`

Register strongly typed tools and use them from a workflow step. Expect to see tool call and tool result events in the run history plus a final purchasing decision in context, which demonstrates what typed tool use looks like when replayed step by step.

```bash
replayt run examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

## 5. Retries for flaky integrations — `examples.e05_retrying_vendor_lookup`

Show how a state can retry automatically before succeeding. Expect the event log to show one or more failed attempts followed by a later success, so readers can see exactly how retries appear in `inspect` output without hidden control flow.

```bash
replayt run examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

## 6. Sales call prep brief — `examples.e06_sales_call_brief`

Use structured LLM output to turn CRM notes into a call brief. Expect a validated brief with fields such as account summary, risks, and talking points rather than free-form prose, which helps readers understand the library's schema-first LLM pattern.

```bash
replayt run examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

## 7. Customer feedback clustering — `examples.e07_feedback_clustering`

Use the LLM for batch summarization and prioritization. Expect clustered themes and a prioritized summary of the feedback list, giving a realistic example of how replayt captures structured model output for multi-item analysis.

```bash
replayt run examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

## 8. Travel approval — `examples.e08_travel_approval`

Evaluate travel policy automatically, then pause for manager approval only when policy flags require it. Expect either an automatic pass for policy-compliant trips or, for the sample input, a paused run waiting on `manager_review`, which shows how approval gates surface in normal CLI usage.

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

Combine typed tools with an executive approval gate for sev1 communications. Expect enrichment and decision steps in the log plus, for high-severity incidents, a pause awaiting `exec_comms` approval before any external communication path can complete.

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

A relatable developer workflow with deterministic validation, LLM classification, and explicit routing. Expect the issue to be classified into a narrow category and routed to a clear next action, so readers can picture how replayt supports developer-facing automations without hiding decisions.

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

## 11. Refund policy workflow — `examples.refund_policy`

A constrained support decision flow where the output space stays narrow and auditable. Expect a bounded refund decision such as approve, deny, or review, along with the policy reasoning encoded in structured state rather than an untraceable natural-language answer.

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"My order arrived damaged and I need a refund.","order":{"order_id":"ORD-1001","amount_cents":12999,"delivered":true,"days_since_delivery":3}}'
```

## 12. Publishing preflight with approval gate — `examples.publishing_preflight`

Check draft copy, generate a structured checklist, and pause for a human publishing decision. Expect the sample draft to trigger a checklist with obvious compliance concerns and then pause for `publish` approval, illustrating how replayt handles human-in-the-loop content review.

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

**Minimal API sketch:** an HTTP server can expose `GET /runs/{run_id}` that streams the JSONL for that run (parse NDJSON lines into a list for the UI). `POST /runs/{run_id}/approvals/{approval_id}` validates the user, then either runs `subprocess.run(["replayt", "resume", target, run_id, "--approval", approval_id], check=True)` or appends one `approval_resolved` line matching the schema your replayt version expects. Use Tailwind (or your stack) for layout if you build HTML—see [`documentation/STYLE.md`](../../documentation/STYLE.md).

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

**Scenario:** You want `openai` package features (custom retries, future betas) without waiting for replayt to wrap everything.

**Approach:** Inside a `@wf.step`, call the SDK directly, then **validate** with Pydantic and `ctx.set(...)`. Optionally emit custom data via `ctx.set` only, or add small helper functions in your repo that write aligned dicts if you standardize on extra event types later.

Keep **transitions and approvals** in replayt; keep **provider SDK** in imperative Python inside the step.

### Pattern: stronger log redaction

**Scenario:** You need structured outputs in logs but want to avoid even short LLM body previews.

**Approach:** Run the CLI with `--log-mode structured_only` (or `LogMode.structured_only` in `Runner`). LLM bodies are not stored; validated `structured_output` events still capture schema-shaped results for audit.

### Pattern: wrap your own HTTP / gateway client

**Scenario:** You need a corporate HTTP proxy, custom signing, or a gateway SDK—more than `OPENAI_BASE_URL` and `extra_headers`—but you still want explicit replayt states.

**Approach:** Keep **`Runner(..., llm_settings=LLMSettings(...))`** for anything the built-in client supports (base URL, timeout, headers). For arbitrary stacks, call your wrapper **inside one `@wf.step`**, validate the result with **Pydantic**, `ctx.set(...)`, and return the next state explicitly. Do not hide transitions inside the wrapper.

### Pattern: golden path test (pytest)

**Scenario:** You want regression tests and “eval-like” checks without a built-in `replayt eval` command.

**Approach:** Call **`Runner.run`** from pytest with **fixed inputs**. Prefer **mocking** `httpx` or injecting a stub so CI needs no API key; assert on `result.status` and keys in the runner’s final context, or parse the JSONL for your `run_id` and assert on `structured_output` events. For human-readable debugging after a failed CI run, point people at **`replayt replay RUN_ID`** with a saved log directory.

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
</think>
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
TodoWrite
