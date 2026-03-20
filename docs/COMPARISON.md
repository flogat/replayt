# How replayt compares (mental migration guide)

replayt is a **small FSM runner, a local JSONL audit log, and a CLI**. Use this page to map tools you already know; it is a migration guide, not a feature parity matrix.

## Plain Python (`if` / `else` + prints)

**You already have:** Full control and no workflow dependency.

**replayt adds:** One event schema (`run_started`, `state_entered`, `llm_request`, …), `replayt inspect` / `replay` / `report`, first-class approvals (exit code `2`), and graph validation for CI. Handlers stay ordinary Python inside `@wf.step`; the graph and logging stay explicit.

**Stay on plain Python for:** One-off scripts where you do not need a shared audit format or replay tooling.

## “Agent” or planner frameworks (e.g. LangGraph-style loops)

**Those stacks** stress flexible graphs, tool routing, and demos that feel autonomous.

**replayt** keeps transitions in code you can read, avoids planners rewriting edges, and **`replayt replay`** follows a **recorded** timeline without calling the provider again. If you use another framework, call it **inside one step**, validate with Pydantic, then `return "next_state"` — see **Pattern: framework in a sandbox step** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**Prefer the other tool when:** You want the framework to own exploration, dynamic graph mutation, or long-lived autonomous sessions.

## Temporal / Cadence / distributed workflow engines

**Temporal and similar engines** ship durable timers, cluster-scale orchestration, and activity retries across process boundaries.

**replayt** runs **one finite run per process** (or one `Runner.run` per queue message), keeps logs local, and supports human approval pause/resume. Cross-job retries, concurrency, and backpressure belong in **your** scheduler (Celery, Airflow, K8s Jobs, SQS) — see **Pattern: queue worker** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**Use Temporal when:** You need distributed durability and workflow code that survives worker crashes as a first-class product feature.

## Hosted LLM “platforms” and observability suites

**Hosted stacks** usually mean accounts, dashboards, and traces on someone else’s infrastructure.

**replayt** stores run history in files you own (JSONL, optional SQLite); core has no cloud requirement. The client is **OpenAI-compatible**; provider and base URL come from environment variables (defaults favor OpenRouter when unset — see [`CONFIG.md`](CONFIG.md)). To feed a vendor pipeline, forward events yourself — **Pattern: custom EventStore for external sinks** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**Use hosted observability when:** Policy mandates a vendor for telemetry; replayt can still be the engine if JSONL remains the source of truth.

## Quick reference

| If you need… | replayt | Often paired with… |
| --- | --- | --- |
| Explicit states in repo | Yes | Code review / CI (`replayt validate`) |
| “What happened?” for one run | Yes | `inspect`, `replay`, `report` |
| Distributed saga across months | No | Temporal, queues, or separate services |
| Autonomous multi-hour agent | No | A different product shape |
| One-run audit trail on disk | Yes | `JSONLStore`, optional SQLite |

For scope and “we won’t add X to core,” see [`SCOPE.md`](SCOPE.md).
