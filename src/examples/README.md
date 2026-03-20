# Examples

Install editable so `examples.*` imports resolve:

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
```

This folder now includes a **progressive tutorial ladder**: start with deterministic, LLM-free workflows and move toward typed tools, retries, structured model output, and approval gates.

## Progression map

### 1. Hello world state machine — `examples.e01_hello_world`
Smallest possible workflow: inject inputs, set context, and finish.

```bash
replayt run examples.e01_hello_world:wf \
  --inputs-json '{"customer_name":"Ava"}'
```

### 2. Normalize a web form — `examples.e02_intake_normalization`
Validate raw request data and derive a clean internal payload.

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

### 8. Travel request approval — `examples.e08_travel_approval`
Policy evaluation followed by a human approval checkpoint.

```bash
replayt run examples.e08_travel_approval:wf \
  --inputs-json '{"trip":{"employee":"Jordan","destination":"Berlin","reason":"Customer workshop","estimated_cost":2650.0,"days_notice":18}}'
# then copy the run_id and approve it:
replayt resume examples.e08_travel_approval:wf "<run_id>" --approval manager_review
```

Reject instead:

```bash
replayt resume examples.e08_travel_approval:wf "<run_id>" --approval manager_review --reject
```

### 9. Incident response coordination — `examples.e09_incident_response`
Blend typed tools, branching severity logic, and an exec approval gate.

```bash
replayt run examples.e09_incident_response:wf \
  --inputs-json '{"incident":{"service":"payments-api","error_rate":18.4,"customer_impact":"checkout failures in US-East","suspected_cause":"database connection exhaustion"}}'
```

### 10. Publishing preflight — `examples.publishing_preflight`
LLM checklist + approval gate for content operations.

```bash
replayt run examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
# copy run_id from output, then:
replayt resume examples.publishing_preflight:wf "<run_id>" --approval publish
replayt replay "<run_id>"
```

Reject instead of approve:

```bash
replayt resume examples.publishing_preflight:wf "<run_id>" --approval publish --reject
```

## Existing focused examples

### GitHub issue triage — `examples.issue_triage`

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, it throws. v1.2."}}'
```

### Support refund policy — `examples.refund_policy`

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"Customer says package never arrived","order":{"order_id":"A-1","amount_cents":4999,"delivered":false,"days_since_delivery":0}}'
```

## Graph export

```bash
replayt graph examples.e04_tool_using_procurement:wf
```
