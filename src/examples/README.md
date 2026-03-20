# Examples

These examples are meant to show what replayt is good at:

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

## A. GitHub issue triage

A relatable developer workflow with deterministic routing.

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

Then inspect what happened:

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

## B. Refund policy workflow

A constrained support decision flow where the output space stays narrow and auditable.

```bash
replayt run examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

### 3. Route a support ticket — `examples.e03_support_routing`
A deterministic branching flow for support operations.

```bash
replayt run examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

### 4. Typed tool calls — `examples.e04_tool_using_procurement`
Register strongly-typed tools and use them from a workflow step.

```bash
replayt run examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

### 5. Retries for flaky integrations — `examples.e05_retrying_vendor_lookup`
Show how a state can retry automatically before succeeding.

```bash
replayt run examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

### 6. Sales call prep brief — `examples.e06_sales_call_brief`
First structured LLM output example: turn CRM notes into a call brief.

```bash
replayt run examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

### 7. Customer feedback clustering — `examples.e07_feedback_clustering`
Use the LLM for batch summarization and prioritization.

```bash
replayt run examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

## C. Publishing preflight with approval gate

A workflow that pauses for a human decision before continuing.

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

## D. Python file target

replayt can load a workflow directly from a Python file if it exports `wf` or `workflow`.

```bash
replayt run workflow.py --inputs-json '{"ticket":"hello"}'
```

## E. YAML workflow target

For small declarative flows, replayt can run a workflow directly from YAML.

```bash
replayt run workflow.yaml --inputs-json '{"route":"refund","ticket":"where is my order?"}'
```

## F. Graph export

```bash
replayt graph examples.e04_tool_using_procurement:wf
```
