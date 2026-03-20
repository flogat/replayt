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
```

## 1. Hello world — `examples.e01_hello_world`

The smallest workflow in the tutorial set. It writes a greeting and a next action into context so you can inspect and replay the run.

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

```bash
replayt run examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

## 3. Support routing — `examples.e03_support_routing`

A deterministic branching flow for support operations.

```bash
replayt run examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

## 4. Typed tool calls — `examples.e04_tool_using_procurement`

Register strongly typed tools and use them from a workflow step.

```bash
replayt run examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

## 5. Retries for flaky integrations — `examples.e05_retrying_vendor_lookup`

Show how a state can retry automatically before succeeding.

```bash
replayt run examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

## 6. Sales call prep brief — `examples.e06_sales_call_brief`

Use structured LLM output to turn CRM notes into a call brief.

```bash
replayt run examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

## 7. Customer feedback clustering — `examples.e07_feedback_clustering`

Use the LLM for batch summarization and prioritization.

```bash
replayt run examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

## 8. Travel approval — `examples.e08_travel_approval`

Evaluate travel policy automatically, then pause for manager approval only when policy flags require it.

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

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

## 11. Refund policy workflow — `examples.refund_policy`

A constrained support decision flow where the output space stays narrow and auditable.

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"My order arrived damaged and I need a refund.","order":{"order_id":"ORD-1001","amount_cents":12999,"delivered":true,"days_since_delivery":3}}'
```

## 12. Publishing preflight with approval gate — `examples.publishing_preflight`

Check draft copy, generate a structured checklist, and pause for a human publishing decision.

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
</think>
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
TodoWrite
