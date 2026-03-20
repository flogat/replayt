# Examples

These examples are meant to be read like a tutorial, not just a command catalog.

Each section below tries to answer four questions:

- **Why does this example exist?**
- **What does the workflow code do?**
- **What command should you run?**
- **What should you expect to see after it runs?**

If you are new to replayt, start with [`docs/QUICKSTART.md`](../../docs/QUICKSTART.md), then read the sections below **in order**. There are **14** runnable workflows here (sections 1–12, plus OpenAI and Anthropic SDK examples). They move from a two-step deterministic run to LLM-backed classification, typed tools, retries, and approval gates. By the later sections, you should be comfortable opening each source file, reading the state handlers, and mapping that code to the events you see in `inspect` and `replay`.

**Patterns and recipes** (approval bridge, batch driver, async apps, dashboards, encryption sketches, …) are in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)**—kept separate so this page reads as a straight-line tutorial.

<p align="center">
  <img src="../../docs/demo-why.svg" alt="typical agent framework vs replayt" width="820"/>
</p>

## How to use this tutorial README

A productive rhythm is:

1. Read one section in this file.
2. Open the corresponding source file in `src/replayt_examples/`.
3. Run the example exactly as shown.
4. Inspect the run and compare the resulting context and events with the explanation here.
5. Change the sample input and run it again to see how the workflow behaves.

### Install (PyPI — no clone required)

```bash
pip install replayt
# pip install replayt[yaml]  # if you run .yaml / .yml workflow targets
replayt doctor
export OPENAI_API_KEY=...   # only for sections that call a live model
```

Runnable tutorials ship in the **`replayt_examples`** package on PyPI (namespaced so it does not collide with a generic `examples` module in your own code).

### Install (from this repository)

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
# Optional: load from .env in your shell (replayt does not read .env by itself)
# set -a && source .env && set +a   # bash, if .env is export-safe
# direnv allow                        # if you use direnv + .envrc
```

See [`README.md`](../../README.md) for Windows activation lines, `replayt doctor`, optional extras (`[yaml]`), and LLM env vars (`OPENAI_BASE_URL`, `REPLAYT_MODEL`).

## Tests without a live LLM (CI and pytest)

Sections **1–5** of this tutorial need **no API key**. For LLM-backed workflows in **automated tests**, use **`MockLLMClient`** with **`run_with_mock`** (or mock `httpx`) and assert on context or JSONL events—see **Pattern: golden path test (pytest)** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md). For **`replayt validate`** and CI exit codes, see [`docs/RECIPES.md`](../../docs/RECIPES.md).

## When core ends: streaming, hooks, approvals, and audit integrity

replayt’s contract is explicit states, an append-only **JSONL** timeline, and structured LLM outputs—use **`ctx.llm.with_settings(...)`** when you need per-call overrides so they show up under **`effective`** on **`llm_request`** events. Core does **not** emit per-token streams as first-class log lines (that would flood the timeline and blur replay semantics); instead, stream inside a step and record a **Pydantic-validated** result or a small summary you control. Terminal **`replayt resume`** is enough for many teams; stakeholder-facing or SSO-adjacent approvals stay in **your** app that reads the same JSONL and resolves gates without changing replayt’s graph. Org notifications, trace IDs, and policy checks should live in outer wrappers or callbacks so the FSM is never a hidden second engine. Tamper-evident or compliance-heavy bundles mean hashing, encrypting, or archiving **your** log files—the runtime cannot cryptographically prove integrity if an attacker can write the log directory (see **Security and trust boundaries** in the main [`README.md`](../../README.md)).

**Composition patterns** (copy the names into EXAMPLES_PATTERNS search):

- **Pattern: stream inside step, log structured summary** — streaming UX without core token events.
- **Pattern: approval bridge (local UI)** — web or chat approvals while replayt stays the engine.
- **Pattern: webhook / lifecycle callbacks** — notifications and policy hooks without an observability platform in core.
- **Pattern: encrypted run logs** and **Pattern: post-hoc PII scrub on JSONL files** — stronger disk posture and redaction.

Share a read-only timeline for review without building a server:

```bash
replayt replay <run_id> --format html --out run.html
```

Optional **line/file SHA-256 manifest** for a JSONL run (best-effort audit packet; not proof against someone who can edit the log dir):

```bash
replayt seal <run_id>
```

For **in-process** trace IDs or policy logging, use **`Runner(..., before_step=..., after_step=...)`** in Python (see **Pattern: webhook / lifecycle callbacks** for outer-wrapper alternatives).

### Framework-style agents, streaming, and planner loops (feature 10 / composition)

This subsection is the **documentation-first** answer for “why isn’t streaming / LangChain / LangGraph built into the runner?” replayt keeps **explicit** states and append-only JSONL; per-token log lines and hidden planners are out of scope ([**docs/SCOPE.md**](../../docs/SCOPE.md)). The supported shape is always: **one step** wraps the fancy SDK or graph; **one** validated exit shape drives the next state.

### LangGraph (and similar frameworks) — **composition**, not core

replayt will not ship LangGraph inside the runner; that would hide control flow and fight the explicit FSM model (see the **LangChain / LangGraph** row in **[docs/SCOPE.md](../../docs/SCOPE.md)**). **Recommended shape:** run LangGraph **inside one `@wf.step`**, then transition replayt based on **one** Pydantic-shaped outcome (or a small summary you write to context). Stream tokens and run planner loops **inside** that handler; log **final** structured data via `ctx.llm.parse(...)`, `structured_output` events, or tools—not every planner tick.

Install graph libraries in **your** project only:

```bash
pip install langgraph langchain-core
```

Illustrative pattern (adapt imports and graph build to your codebase):

```python
from pydantic import BaseModel

class AgentChunkOut(BaseModel):
    answer: str
    route: str

@wf.step("with_langgraph")
def with_langgraph(ctx):
    from langgraph.graph import StateGraph  # type: ignore[import-untyped]

    # graph = ... build StateGraph, .compile(), etc.
    # result = graph.invoke({"messages": ctx.get("messages", [])})
    result = {"answer": "stub", "route": "done"}  # replace with real invoke()
    out = AgentChunkOut.model_validate(
        {"answer": str(result.get("answer", ""))[:4000], "route": str(result.get("route", "done"))}
    )
    ctx.set("last_agent", out.model_dump())
    return out.route if out.route in {"done", "retry"} else "done"
```

Human gates stay replayt-native: **`ctx.request_approval`** or the **Pattern: approval bridge** in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)**.

## 1. Hello world — `replayt_examples.e01_hello_world`

Start here if you want the absolute minimum replayt workflow.

### What the code does

This example has only two states: `greet` and `done`.

- `greet` reads `customer_name` from context.
- It writes a friendly `message` plus a `next_action` hint back into context.
- It transitions directly to `done`.
- `done` sets `completed=true` and returns `None`, which ends the workflow.

This is the example to use when you want to understand the core replayt model: a named state reads context, writes context, and returns the next state explicitly.

### What to run
The smallest workflow in the tutorial set. It writes a greeting and a next action into context so you can inspect and replay the run.

Expected outcome: the run completes successfully and the final context includes `message="Hello, Sam! Your first replayt workflow ran."`, `next_action="Inspect this run, then replay it from the CLI."`, and `completed=true`, so you can compare a finished run against later, more complex examples.

```bash
replayt run replayt_examples.e01_hello_world:wf \
  --inputs-json '{"customer_name":"Sam"}'
```

Then inspect what happened:

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

### What to expect

The run should complete successfully in a very small number of events. The final context should include:

- `message="Hello, Sam! Your first replayt workflow ran."`
- `next_action="Inspect this run, then replay it from the CLI."`
- `completed=true`

Use this section to get comfortable with the idea that even a tiny workflow produces a replayable execution history.

## 2. Intake normalization — `replayt_examples.e02_intake_normalization`

This example introduces a very common workflow pattern: validate raw input first, then transform it into a cleaner internal representation.

### What the code does

The workflow has three stages in spirit, although only two state handlers do real work:

- `validate` checks that `lead` exists and matches the `RawLead` Pydantic schema.
- `normalize` trims whitespace, title-cases the name, lowercases the email, compresses message spacing, and derives a `segment`.
- `done` ends the run.

The important lesson is that replayt is not just for LLM calls. It is also useful for deterministic business logic that you want to inspect later.

### What to run
Validate a raw lead payload, normalize formatting, and derive an internal segment.

Expected outcome: the run completes successfully and stores `normalized_lead` with `name="Sam Patel"`, `email="sam@example.com"`, `company="Northwind"`, a whitespace-normalized message, and `segment="enterprise"` because the sample message mentions a demo for many seats.

```bash
replayt run replayt_examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

### What to expect

The run should complete successfully and preserve both the validated input and the normalized output in context. In particular, `normalized_lead` should contain:

- `name="Sam Patel"`
- `email="sam@example.com"`
- `company="Northwind"`
- `message="Need a demo for 40 seats"`
- `segment="enterprise"`

The `segment` becomes `enterprise` because the normalization logic checks whether the message mentions `seat` or `demo`. This is a good example of deterministic branching based on explicit code instead of a model guess.

## 3. Support routing — `replayt_examples.e03_support_routing`

This example shows explicit branching for operational workflows.

### What the code does

The workflow validates the incoming `ticket`, then derives a routing decision from plain rules:

- security keywords route to the `security` queue with `urgent` priority
- billing keywords route to the `billing` queue
- bug/error keywords route to the `technical` queue
- enterprise or VIP customers can raise the priority even if the queue stays the same

Finally, the workflow writes a `routing_decision` dictionary with queue, priority, and SLA hours.

### What to run
A deterministic branching flow for support operations.

Expected outcome: the run completes successfully and writes `routing_decision` with `queue="billing"`, `priority="high"`, and `sla_hours=4` because the sample ticket mentions payment failure and the customer tier is `enterprise`.

```bash
replayt run replayt_examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

### What to expect

The sample input contains billing language (`payment`, `invoice`, `declined`) and an enterprise customer tier. That means the final `routing_decision` should be:

- `queue="billing"`
- `priority="high"`
- `sla_hours=4`

This is a useful tutorial example because you can easily change the subject/body and watch the route change in predictable ways.

## 4. Typed tool calls — `replayt_examples.e04_tool_using_procurement`

This example introduces replayt's typed tool system.

### What the code does

Inside the `intake` step, the workflow registers two tools:

- `calculate_total(unit_price, quantity)` computes the purchase total
- `budget_policy(query: BudgetPolicyInput)` checks the department's spending limit

After validating the purchase request, the `evaluate` step calls those tools through `ctx.tools.call(...)` rather than invoking ad hoc helper functions. That means the tool activity is captured in the run history.

### What to run
Register strongly typed tools and use them from a workflow step.

Expected outcome: the run completes successfully, the event log shows typed calls to `calculate_total` and `budget_policy`, and the final `decision` records `total_cost=298.0`, `within_policy=true`, and `recommended_action="auto_approve"` for the sample Design request.

```bash
replayt run replayt_examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

### What to expect

The run should complete successfully and the event log should show both tool call and tool result events. In final context, `decision` should look roughly like this:

- `employee="Maya"`
- `item="monitor arm"`
- `total_cost=298.0`
- `within_policy=true`
- `recommended_action="auto_approve"`

The Design department limit in the example code is `500.0`, so a total of `298.0` stays within policy. This makes the example a good tutorial for both typed tools and deterministic post-tool branching.

## 5. Retries for flaky integrations — `replayt_examples.e05_retrying_vendor_lookup`

This example demonstrates retries without hidden loops.

### What the code does

The `lookup` step is decorated with a retry policy of up to three attempts. The implementation intentionally simulates a flaky dependency:

- it increments `lookup_attempts`
- it throws a temporary error on the first attempt
- it succeeds on the second attempt by storing `vendor_record`

The `summarize` step then copies the vendor record into `lookup_summary` and includes the attempt count.

### What to run
Show how a state can retry automatically before succeeding.

Expected outcome: the first `lookup` attempt fails with a temporary timeout, replayt retries automatically, the second attempt succeeds, and `lookup_summary` ends with `vendor_name="Acme Fulfillment"`, `status="active"`, `payment_terms="net-30"`, `risk_level="low"`, and `lookup_attempts=2`.

```bash
replayt run replayt_examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

### What to expect

You should see a failed `lookup` attempt followed by an automatic retry and then a successful continuation into `summarize`. The final `lookup_summary` should include:

- `vendor_name="Acme Fulfillment"`
- `status="active"`
- `payment_terms="net-30"`
- `risk_level="low"`
- `lookup_attempts=2`

The point of this tutorial is that the retry behavior is visible and auditable. replayt is not hiding the failure; it is recording it as part of the workflow history.

## 6. Sales call prep brief — `replayt_examples.e06_sales_call_brief`

This is the first example where the model produces a structured object.

### What the code does

The workflow defines a `CallBrief` schema with these fields:

- `customer_stage`
- `top_goals`
- `risks`
- `recommended_talking_points`
- `next_step`

The single working state, `draft_brief`, sends the account name and CRM notes to `ctx.llm.parse(...)`. replayt then validates the model output against the schema before storing it in context as `call_brief`.

### What to run
Use structured LLM output to turn CRM notes into a call brief.

Expected outcome: the run completes successfully and `call_brief` validates against the `CallBrief` schema, so `inspect` shows structured fields such as `customer_stage`, `top_goals`, `risks`, `recommended_talking_points`, and `next_step` instead of an unstructured paragraph.

```bash
replayt run replayt_examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

### What to expect

The exact wording will vary by model, but the outcome should still be predictable in shape. The run should complete successfully and `call_brief` should always be a schema-valid object rather than raw free-form text. In practice you should expect:

- a `customer_stage` consistent with active evaluation or procurement
- goals related to the pilot and security review
- risks related to SOC 2 confirmation or rollout timing
- talking points that help the seller prepare for the next conversation
- a concise `next_step`

This is a tutorial example for the difference between “model output exists” and “model output is constrained enough to drive a workflow.”

## 7. Customer feedback clustering — `replayt_examples.e07_feedback_clustering`

This example scales the same structured-output idea to a list of inputs instead of one note.

### What the code does

The workflow defines two schemas:

- `FeedbackTheme`, which captures one theme, its priority, supporting quotes, and a recommended owner
- `FeedbackSummary`, which collects all themes and a `release_note_hint`

The `cluster` step passes the whole feedback list to the model and asks for a structured summary.

### What to run
Use the LLM for batch summarization and prioritization.

Expected outcome: the run completes successfully and `feedback_summary` contains a schema-validated list of themes plus a `release_note_hint`; for the sample input you should expect themes around exports/performance and identity access (Okta SSO), each with priorities and suggested owners.

```bash
replayt run replayt_examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

### What to expect

Again, the exact wording depends on the model, but the structure should stay stable. `feedback_summary` should contain:

- a list of themes in `themes`
- for each theme, a `priority`, `representative_quotes`, and `recommended_owner`
- a single `release_note_hint`

For this sample input, likely themes include performance/export reliability and access management or SSO. This makes the example useful for understanding how replayt captures structured analysis over multiple pieces of text.

## 8. Travel approval — `replayt_examples.e08_travel_approval`

This example introduces a human approval gate.

### What the code does

The workflow has three important phases:

- `policy_check` validates the trip request and computes policy flags
- `manager_review` either auto-approves, pauses for approval, or routes to rejection based on approval state
- `book_trip` and `reject_trip` write the final status

The sample input is intentionally chosen to trigger review because it violates two simple policy checks: high estimated cost and short notice.

### What to run
Evaluate travel policy automatically, then pause for manager approval only when policy flags require it.

Expected outcome: with the sample input the run pauses with exit code 2 after `policy_check` stores `policy_flags=["high_cost", "late_notice"]` and requests `manager_review`; after approval it finishes with `travel_status="approved_for_booking"`, and after rejection it finishes with `travel_status="rejected"`.

```bash
replayt run replayt_examples.e08_travel_approval:wf \
  --inputs-json '{"trip":{"employee":"Sam Patel","destination":"New York","reason":"Customer onsite kickoff","estimated_cost":3200.0,"days_notice":5}}'
```

Approve it:

```bash
replayt resume replayt_examples.e08_travel_approval:wf <run_id> --approval manager_review
```

Reject it instead:

```bash
replayt resume replayt_examples.e08_travel_approval:wf <run_id> --approval manager_review --reject
```

### What to expect

On the first run, replayt should pause with exit code `2`. Before it pauses, the workflow should store:

- `travel_policy.auto_approvable=false`
- `travel_policy.policy_flags=["high_cost", "late_notice"]`

It then requests approval `manager_review` with a summary that includes the employee, destination, and flags.

If you approve the run, it should resume through `book_trip` and end with `travel_status="approved_for_booking"`.

If you reject the run, it should resume through `reject_trip` and end with `travel_status="rejected"`.

This is one of the best examples for learning how paused workflows appear in normal CLI usage.

## 9. Incident response — `replayt_examples.e09_incident_response`

This example combines typed tools, deterministic severity logic, and an approval gate.

### What the code does

The workflow proceeds through four conceptual stages:

- `assess` validates the incident and assigns severity from the error rate
- `stabilize` uses tools to page on-call staff and draft a status page update
- `exec_review` decides whether external communications require approval
- `announce` or `internal_only` records the final communication plan

For sev1 incidents, the workflow pauses for an executive communications decision. Lower-severity incidents skip that approval path.

### What to run
Combine typed tools with an executive approval gate for sev1 communications.

Expected outcome: the sample incident is classified as `sev1` because `error_rate=12.5`, the run logs tool calls for paging and status-page draft creation, then pauses for `exec_comms`; approving resumes to `communication_plan="external_statuspage_and_internal_slack"`, while rejecting resumes to `communication_plan="internal_updates_only"`.

```bash
replayt run replayt_examples.e09_incident_response:wf \
  --inputs-json '{"incident":{"service":"api","error_rate":12.5,"customer_impact":"Checkout requests are failing for many customers.","suspected_cause":"Database connection pool exhaustion"}}'
```

For a sev1 incident, approve external comms:

```bash
replayt resume replayt_examples.e09_incident_response:wf <run_id> --approval exec_comms
```

Or keep the response internal-only:

```bash
replayt resume replayt_examples.e09_incident_response:wf <run_id> --approval exec_comms --reject
```

### What to expect

With `error_rate=12.5`, the sample incident is `sev1`. That means the run should:

- store `severity="sev1"`
- log a tool call to `page_on_call`
- log a tool call to `create_statuspage_draft`
- pause on approval `exec_comms`

If approved, the final context should include `communication_plan="external_statuspage_and_internal_slack"`.

If rejected, the final context should include `communication_plan="internal_updates_only"`.

This tutorial example shows how replayt keeps even high-pressure operational flows explicit and replayable.

## 10. GitHub issue triage — `replayt_examples.issue_triage`

<p align="center">
  <img src="../../docs/demo.svg" alt="replayt demo: run, inspect, replay on issue triage" width="820"/>
</p>

This example shows how deterministic validation and LLM classification can work together.

### What the code does

The workflow starts with `validate`, which ensures the issue payload exists and checks for obviously incomplete title/body fields. It then moves to `classify`:

- if required fields are missing, the workflow avoids an LLM classification and routes to `respond`
- otherwise, the model produces a `TriageDecision`
- if the model says more information is needed, the workflow still routes to `respond`
- if not, the workflow routes to `route`

The `route` step turns that decision into a smaller `routing` object with queue, label, and priority.

### What to run
A relatable developer workflow with deterministic validation, LLM classification, and explicit routing.

Expected outcome: the sample issue passes validation, the LLM returns a `TriageDecision`, and the final context either contains a `response_template` asking for clarification or, more likely for this sample, a `routing` object with a category-backed queue, suggested label, and priority for engineering triage.

```bash
replayt run replayt_examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

### What to expect

The sample input is long enough to pass validation, so the interesting behavior happens in classification. The final context should contain one of two outcomes:

- `response_template` if the model decides more information is needed
- `routing` if the model is confident enough to classify and route

For this particular issue, a bug-style classification and engineering-oriented routing are the most likely result. The key tutorial lesson is that replayt still keeps the control flow explicit even when a model is involved.

## 11. Refund policy workflow — `replayt_examples.refund_policy`

<p align="center">
  <img src="../../docs/demo-debug.svg" alt="replayt debugging a failed refund_policy run" width="820"/>
</p>

This example shows a constrained customer-support decision with structured LLM output.

### What the code does

The workflow:

- validates `ticket` and `order` in `ingest`
- asks the model for a schema-valid `RefundDecision` in `decide`
- copies the relevant fields into `summary_for_agent` in `summarize`

The prompt intentionally narrows the policy space: refund, reship, store credit, deny, or escalate.

### What to run
A constrained support decision flow where the output space stays narrow and auditable.

Expected outcome: the run completes successfully and `summary_for_agent` contains the schema-validated refund action, reason codes, and customer message; for the sample damaged-order ticket delivered 3 days ago, a refund-oriented outcome is plausible under the stated policy, but the exact action still comes from the model and remains auditable in the log.

```bash
replayt run replayt_examples.refund_policy:wf \
  --inputs-json '{"ticket":"My order arrived damaged and I need a refund.","order":{"order_id":"ORD-1001","amount_cents":12999,"delivered":true,"days_since_delivery":3}}'
```

### What to expect

The model still has discretion, but it must answer inside a bounded schema. After the run, `summary_for_agent` should contain:

- `action`
- `reason_codes`
- `customer_message`

Because the order was delivered only 3 days ago and the ticket reports damage, a refund-friendly action is plausible under the stated policy. The most important tutorial takeaway is that the output remains structured and reviewable rather than hidden inside prose.

## 12. Publishing preflight with approval gate — `replayt_examples.publishing_preflight`

<p align="center">
  <img src="../../docs/demo-approval.svg" alt="replayt approval gate: pause, review, resume" width="820"/>
</p>

This example combines structured LLM review with a human publication decision.

### What the code does

The `checklist` state asks the model to evaluate a draft against a strict checklist and return a `ChecklistResult` object. The workflow stores that result, builds an `approval_summary`, and then moves into `approval`.

The `approval` state behaves much like the travel example:

- if already approved, continue to `finalize`
- if rejected, continue to `abort`
- otherwise pause and request `publish`

### What to run
Check draft copy, generate a structured checklist, and pause for a human publishing decision.

Expected outcome: the sample draft produces a checklist with one or more issues about unsupported or risky claims, then pauses for `publish` approval; approving resumes to `publish_status="approved"`, while rejecting resumes to `publish_status="aborted"`.

```bash
replayt run replayt_examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
```

Approve it:

```bash
replayt resume replayt_examples.publishing_preflight:wf <run_id> --approval publish
```

Reject it instead:

```bash
replayt resume replayt_examples.publishing_preflight:wf <run_id> --approval publish --reject
```

### What to expect

The sample draft is intentionally risky, so the checklist should likely report `passes=false` and one or more issues related to unsupported claims or inappropriate guarantees. The first run should then pause for `publish` approval.

If approved, the resumed run should end with `publish_status="approved"`.

If rejected, the resumed run should end with `publish_status="aborted"`.

This is a good tutorial example for content review pipelines where an LLM can prepare structured guidance, but a human still makes the final go/no-go decision.

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
replayt graph replayt_examples.e04_tool_using_procurement:wf
```

---

## 13. OpenAI SDK integration — `replayt_examples.e10_openai_sdk_integration`

A full integration example using the official `openai` Python SDK inside replayt steps: function calling with Pydantic validation, the `tools` parameter, and streaming with a structured summary pass. Transitions and approvals stay in replayt; the SDK lives inside individual step handlers. Requires `pip install openai`.

```bash
replayt run replayt_examples.e10_openai_sdk_integration:wf \
  --inputs-json '{"issue_title":"Login page crashes on mobile","issue_body":"Steps: open login on iOS Safari, tap submit, white screen."}'
```

## 14. Anthropic native SDK — `replayt_examples.e11_anthropic_native`

A workaround pattern for developers who want `anthropic.Anthropic()` directly instead of an OpenAI-compatible proxy. LLM traffic from native SDKs is **not** auto-logged by replayt — validated `ctx.set` outputs are your audit surface. Requires `pip install anthropic`.

```bash
replayt run replayt_examples.e11_anthropic_native:wf \
  --inputs-json '{"text":"The new dashboard is fast and intuitive, but the export feature keeps timing out on large datasets."}'
```


---

**Composition patterns** (approval bridge, batch drivers, async/Webhook workarounds, DuckDB, encryption sketches, …) live in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)** so this file stays a linear tutorial.
