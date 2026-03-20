# How replayt compares (mental migration guide)

replayt is a **small FSM runner + local JSONL audit log + CLI**. Use this page to map from tools you already know—not to claim feature parity.

## Plain Python (`if` / `else` + prints)

**You already have:** full control, zero dependencies.

**replayt adds:** a single event schema (`run_started`, `state_entered`, `llm_request`, …), `replayt inspect` / `replay` / `report`, first-class approvals (exit code `2`), and graph validation for CI. You still write normal Python inside `@wf.step` handlers; the graph and logging are conventional.

**When to stay on plain Python:** one-off scripts, no need for shared audit format or replay UI.

## “Agent” or planner frameworks (e.g. LangGraph-style loops)

**Those stacks optimize for:** flexible graphs, tool routing, demos that feel autonomous.

**replayt optimizes for:** transitions you can read in code, no planner rewriting edges, and a **recorded** timeline you can walk without calling the provider again. If you must use another framework, the recommended composition is **one foreign stack call inside one step**, then validate to Pydantic and `return "next_state"` explicitly—see **Pattern: framework in a sandbox step** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**When to prefer the other tool:** you want the framework to own exploration, dynamic graph mutation, or long-lived autonomous sessions.

## Temporal / Cadence / distributed workflow engines

**They provide:** durable timers, cluster-scale orchestration, activity retries across process boundaries.

**replayt provides:** **one finite run per process** (or one `Runner.run` per queue message), local logs, human approval pause/resume. Cross-job retries, concurrency, and backpressure belong in **your** scheduler (Celery, Airflow, K8s Jobs, SQS)—see **Pattern: queue worker** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**When to use Temporal:** you need distributed durability and workflow code that survives worker crashes as a first-class product feature.

## Hosted LLM “platforms” and observability suites

**They provide:** accounts, dashboards, hosted traces.

**replayt provides:** files you own (JSONL, optional SQLite), no cloud requirement in core, and optional forwarding patterns if you want to push events elsewhere—see **Pattern: custom EventStore for external sinks** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**When to use hosted observability:** org mandates a vendor for all telemetry; replayt still works as the engine if you treat JSONL as source of truth.

## Summary

| If you need… | replayt | Often paired with… |
|--------------|---------|-------------------|
| Explicit states in repo | Yes | Your code review / CI (`replayt validate`) |
| “What happened?” for one run | Yes | `inspect`, `replay`, `report` |
| Distributed saga across months | No | Temporal, queues, or separate services |
| Autonomous multi-hour agent | No | Different product shape |
| One-run audit trail on disk | Yes | `JSONLStore`, optional SQLite |

For scope boundaries and “we won’t add X to core,” see [`SCOPE.md`](SCOPE.md).
