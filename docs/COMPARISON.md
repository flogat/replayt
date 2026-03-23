# How replayt compares

replayt is a **small FSM runner, a local JSONL audit log, and a CLI**. This page maps it to tools you may already use. It is a migration guide, not a feature parity matrix.

## Plain Python (`if` / `else` + prints)

**You already have:** Full control and no workflow dependency.

**replayt adds:** One event schema (`run_started`, `state_entered`, `llm_request`, ...), `replayt inspect` / `replay` / `report`, first-class approvals (exit code `2`), and graph validation for CI. Handlers stay ordinary Python inside `@wf.step`; the graph and logging stay explicit.

**Stay on plain Python for:** One-off scripts where you do not need a shared audit format or replay tooling.

## "Agent" or planner frameworks (e.g. LangGraph-style loops)

### LangGraph and similar frameworks

[LangGraph](https://github.com/langchain-ai/langgraph) fits when you want the **framework** to own exploration, dynamic graph mutation, or long-lived autonomous sessions.

**replayt** keeps transitions in code you can read, stores the run in JSONL, and replays that recorded timeline with **`replayt replay`**.

**If you need another framework:** keep it **inside one `@wf.step`**. Validate one Pydantic outcome, then `return "next_state"`; see **Pattern: framework in a sandbox step** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

## Temporal / Cadence / distributed workflow engines

**Temporal and similar engines** ship durable timers, cluster-scale orchestration, and activity retries across process boundaries.

**replayt** runs **one finite run per process** (or one `Runner.run` per queue message), keeps logs local, and supports human approval pause/resume. Cross-job retries, concurrency, and backpressure belong in **your** scheduler (Celery, Airflow, K8s Jobs, SQS); see **Pattern: queue worker** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**Use Temporal when:** You need distributed durability and workflow code that survives worker crashes as a first-class product feature.

## Hosted LLM "platforms" and observability suites

**Hosted stacks** usually mean accounts, dashboards, and traces in a vendor service.

**replayt** stores run history in files you own (JSONL, optional SQLite); core has no cloud requirement. The client is **OpenAI-compatible**; provider and base URL come from environment variables (unset `REPLAYT_PROVIDER` uses the **ollama** preset toward `127.0.0.1:11434`; see [`CONFIG.md`](CONFIG.md)). To feed a vendor pipeline, forward events yourself; see **Pattern: custom EventStore for external sinks** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

**Use hosted observability when:** Policy mandates a vendor for telemetry; replayt can still be the engine if JSONL remains the source of truth.

## Reference table

| If you need... | replayt | Often paired with... |
| --- | --- | --- |
| Explicit states in repo | Yes | Code review / CI (`replayt validate`) |
| "What happened?" for one run | Yes | `inspect`, `replay`, `report` |
| Distributed saga across months | No | Temporal, queues, or separate services |
| Autonomous multi-hour agent | No | A different product shape |
| One-run audit trail on disk | Yes | `JSONLStore`, optional SQLite |

For scope and the things we keep out of core, see [`SCOPE.md`](SCOPE.md).
