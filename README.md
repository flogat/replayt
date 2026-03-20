# replayt

> **Deterministic LLM workflows you can replay.**

**replayt** is a tiny Python library and CLI for developers who want to use LLMs in real workflows **without** adopting a sprawling agent framework, hosted platform, no-code builder, or “AI operating system.”

The core idea is simple:

> If a workflow matters, it should be explicit, inspectable, and replayable.

That is the entire pitch.

replayt gives you a small, strict workflow runner where:

- states are explicit
- transitions are explicit
- structured outputs are schema-validated
- tool calls are typed and logged
- approval gates are first-class
- run history is stored locally
- past runs can be inspected and replayed step by step

If you cannot explain **what happened**, **why it happened**, and **how to replay it**, the workflow is not done yet.

---

## Why replayt exists

Most LLM tooling drifts toward autonomy, hidden loops, framework sprawl, and runtime behavior that feels clever in demos but slippery in production.

replayt goes in the opposite direction.

It is for developers who do **not** want:

- open-ended agent behavior
- silent model improvisation over control flow
- unclear branching
- magical orchestration
- broad abstraction layers that dominate the application

Instead, replayt is built around a boring, disciplined proposition:

- define the workflow explicitly
- validate meaningful outputs strictly
- log the run locally
- inspect every important event
- replay the exact execution history later

The goal is not maximum capability.

The goal is **clarity, control, and trust**.

---

## What replayt is

replayt is a **finite-state-machine-first runtime for LLM workflows**.

A workflow can include:

- explicit named states
- explicit transitions
- strict Pydantic outputs
- typed tool invocations
- deterministic branching rules
- retry and failure policies
- optional human approval checkpoints
- local JSONL and/or SQLite logs
- replayable execution history
- Mermaid graph export
- a CLI for running, inspecting, resuming, replaying, and listing runs

A good replayt workflow lets you answer, after the fact:

- What state did the workflow enter?
- What did the model return?
- Which schema validated it?
- Which tool was called?
- Why did it branch this way?
- Where did it fail?
- What required human approval?
- Can I replay the run and inspect it step by step?

That “after the fact” understanding is the wedge.

---

## What replayt is not

replayt is intentionally narrow.

It is **not**:

- a general-purpose agent framework
- a multi-agent runtime
- a visual workflow builder
- a hosted observability platform
- a no-code automation tool
- a memory or RAG framework
- an eval suite
- a business process engine for everything
- an “AI workforce” platform
- “Temporal for agents”

This is a deliberate anti-bloat project.

The value of replayt is not breadth.
The value is that it stays small enough to understand in one sitting.

---

## Design principles

### 1. Determinism over autonomy
LLM workflows should behave like systems, not personalities. The model may generate outputs, but it should not silently invent control flow.

### 2. Explicit states over hidden loops
The workflow structure should be obvious in code. No hidden planners, implicit retries, or secret sub-agents.

### 3. Strict schemas over fuzzy outputs
Every meaningful model output should validate against a clear schema. Structured output is the default path, not a nice-to-have.

### 4. Typed tool calls over free-form execution
Tool use should be constrained, validated, and logged as part of the run history.

### 5. Inspectability is part of the product
Logging and replay are not internal implementation details. They are part of the reason the tool exists.

### 6. Local-first by default
No account. No hosted dependency. No cloud requirement in v1.

### 7. Tiny mental model
A new user should be able to understand the architecture quickly and feel that the system is boring in the best possible way.

---

## Current feature set

### Workflow engine

- Python-first workflow definitions with explicit state handlers
- Optional YAML workflow specs for simple declarative flows
- Per-state retry policies
- Transition declarations and runtime transition validation
- Approval pause/resume support

### LLM layer

- OpenAI-compatible chat provider support
- Strict Pydantic schema parsing for structured outputs
- Redacted, structured-only, or full logging modes for model traffic
- Per-call LLM overrides via `ctx.llm.with_settings(...)` (logged as `effective` on each `llm_request` / `llm_response`)

### Tooling

- Typed tool registration and invocation
- Tool call and tool result events in run history

### Persistence and replay

- Local JSONL run logs
- Optional SQLite mirroring
- Human-readable replay timeline
- Raw event inspection
- Local run listing

### CLI

- `replayt init` — scaffold `workflow.py` + `.env.example`
- `replayt run TARGET` — `--output json` for machine-readable result; `--tag key=value`; `--timeout SECONDS`; exit **0** completed, **1** failed, **2** paused
- `replayt inspect RUN_ID` — `--output json` (or legacy `--json`) for summary + events
- `replayt replay RUN_ID` — `--format html` for a shareable Tailwind HTML timeline (`--out path`)
- `replayt resume TARGET RUN_ID --approval ID` — same exit codes as `run`
- `replayt graph TARGET`
- `replayt validate TARGET` — check graph integrity without calling any LLM (CI-friendly)
- `replayt diff RUN_A RUN_B` — compare two runs side by side
- `replayt gc --older-than 90d` — garbage-collect old run logs
- `replayt runs` — `--tag key=value` to filter
- `replayt stats` — aggregate counts, LLM latency, token usage; `--tag key=value` to filter
- `replayt doctor`

`TARGET` can be any of:

- `module:variable`
- `workflow.py`
- `workflow.yaml`
- `workflow.yml`

---

## Quickstart

### Install

Create a virtual environment, install replayt, then verify with `replayt doctor`:

```bash
python -m venv .venv
source .venv/bin/activate  # POSIX
# .venv\Scripts\activate     # Windows cmd.exe
# .venv\Scripts\Activate.ps1 # Windows PowerShell
pip install -e ".[dev]"    # contributors: tests, ruff, PyYAML
# pip install -e ".[yaml]"   # minimal editable + YAML workflows only
# pip install replayt        # when published: add [yaml] if you need YAML targets
export OPENAI_API_KEY=...  # required only for workflows that call a model
replayt doctor
```

Optional dependencies (see [`pyproject.toml`](pyproject.toml)): **`[yaml]`** adds PyYAML for `.yaml` / `.yml` workflow targets; **`[dev]`** adds pytest, ruff, and YAML support for working on the repo.

If you keep secrets in a `.env` file, load them your own way before running replayt (for example `export $(grep -v '^#' .env | xargs)`, [direnv](https://direnv.net/) with `.envrc`, or `python-dotenv` in a wrapper script). replayt does not read `.env` on its own—environment order stays explicit and auditable.

---

## Installation

### Platform-specific virtual environment activation

```bash
# bash / zsh (macOS, Linux, WSL)
python -m venv .venv
source .venv/bin/activate

# fish
python -m venv .venv
source .venv/bin/activate.fish

# Windows cmd.exe
python -m venv .venv
.venv\Scripts\activate.bat

# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Then install replayt:

```bash
pip install -e ".[dev]"   # contributors
# pip install replayt      # end users (add [yaml] for YAML workflow targets)
```

### Loading `.env` files

replayt does **not** read `.env` automatically — this keeps environment precedence explicit and auditable. Pick one approach:

**bash / zsh:**

```bash
set -a && source .env && set +a
```

**PowerShell:**

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
    }
}
```

**direnv** (auto-loads on `cd`):

```bash
# .envrc
dotenv
```

```bash
direnv allow
```

### Check your setup

```bash
replayt doctor
```

`replayt doctor` reports your Python version, installed package version, API key status, provider connectivity, and optional extras. Run it first when something is not working.

### Common errors

| Symptom | Fix |
|---------|-----|
| `OPENAI_API_KEY is not set` | Export your key: `export OPENAI_API_KEY=sk-...` (or load from `.env` as above). |
| `ModuleNotFoundError: No module named 'replayt'` | Activate your virtual environment first, then `pip install -e ".[dev]"`. |
| `python: command not found` or wrong version | Use `python3` explicitly, or check `python --version` (requires Python 3.10+). |
| `pip: command not found` | Use `python -m pip install ...` instead. |
| `SSL: CERTIFICATE_VERIFY_FAILED` (corporate proxy) | Set `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` to your corporate CA bundle, or `pip install pip-system-certs`. |
| `yaml_extra: missing` in `replayt doctor` | Install the YAML extra: `pip install replayt[yaml]` (or `pip install -e ".[yaml]"`). |
| `provider_connectivity: unreachable` | Check `OPENAI_BASE_URL` and network access. Behind a VPN? Try `curl -I $OPENAI_BASE_URL/models`. |

---

### Scaffold a minimal project

```bash
replayt init --path .
replayt run workflow.py --inputs-json '{}'
```

### Run a Python workflow

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Steps: open app, click save, crash. Expected: file writes successfully."}}'
```

### Inspect the run

```bash
replayt inspect <run_id>
replayt replay <run_id>
replayt runs
```

### Export a graph

```bash
replayt graph examples.issue_triage:wf
```

### Run a workflow from a Python file

```bash
replayt run workflow.py --inputs-json '{"ticket":"hello"}'
```

### Run a workflow from YAML

```bash
replayt run workflow.yaml --inputs-json '{"route":"approve"}'
```

---

## Recipe: configure the LLM client (base URL, model, timeouts)

replayt uses a small OpenAI-compatible HTTP client. You can steer it in two layers: **process defaults** and **per-call overrides**.

**Environment (CLI and Python if you omit `llm_settings`):**

- `OPENAI_API_KEY` — required for live model calls
- `OPENAI_BASE_URL` — if unset, defaults to the **`REPLAYT_PROVIDER`** preset base URL, else `https://api.openai.com/v1`
- `REPLAYT_MODEL` — if unset, defaults to the **`REPLAYT_PROVIDER`** preset model, else `gpt-4o-mini`
- `REPLAYT_PROVIDER` — optional preset name: `openai` (default behavior), `ollama`, `groq`, `together`, `openrouter`, `anthropic` (native Anthropic hosts often need an OpenAI-compatible gateway—see [`src/examples/README.md`](src/examples/README.md))

**Python defaults** — pick a preset without memorizing URLs:

```python
import os

from replayt.llm import LLMSettings

LLMSettings.for_provider("ollama")  # local Ollama OpenAI-compat
LLMSettings.for_provider("groq", api_key=os.environ["GROQ_API_KEY"])
```

**`Runner` in Python** — pass `llm_settings` for a non-default base URL, timeout, or headers without changing global env:

```python
import os
from replayt import LogMode, Runner, Workflow
from replayt.llm import LLMSettings
from replayt.persistence import JSONLStore
from pathlib import Path

wf = Workflow("demo", version="1")  # define steps on wf …

runner = Runner(
    wf,
    JSONLStore(Path(".replayt/runs")),
    log_mode=LogMode.redacted,
    llm_settings=LLMSettings(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.example.com/v1",
        model="gpt-4o-mini",
        timeout_seconds=90.0,
        extra_headers={"X-My-Gateway": "team-b"},
    ),
)
```

**Per-call** — tighten one step without forking the library: `ctx.llm.with_settings(model=..., temperature=..., timeout_seconds=..., max_tokens=..., extra_headers={...})`. Overrides appear under `effective` on `llm_request` / `llm_response` events.

For timeouts, retries, or betas exposed only through the official `openai` SDK, keep replayt’s graph and approvals as-is and call the SDK **inside a single step** (see **Pattern: OpenAI Python SDK inside a step** in [`src/examples/README.md`](src/examples/README.md)).

---

## Recipe: replayt in CI

Use **`--output json`** and shell on **exit status** (0 = completed, 1 = failed, 2 = paused / needs approval):

```bash
set -euo pipefail
export OPENAI_API_KEY="${OPENAI_API_KEY:?}"
OUT="$(replayt run mypkg.workflow:wf \
  --inputs-json "{\"id\":\"${GITHUB_RUN_ID}\"}" \
  --output json)"
echo "$OUT"
echo "$OUT" | jq -e '.status == "completed"' >/dev/null
```

For **no API key** in CI, tests should use **`MockLLMClient`** / **`run_with_mock`** (`from replayt.testing import MockLLMClient, run_with_mock`) or mock `httpx`; keep smoke workflows that hit a real provider optional.

---

## A tiny Python example

```python
from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("demo", version="1")
wf.set_initial("hello")

@wf.step("hello")
def hello(ctx):
    ctx.set("message", "replayt")
    return None

runner = Runner(
    wf,
    JSONLStore(Path(".replayt/runs")),
    log_mode=LogMode.redacted,
)

result = runner.run(inputs={"demo": True})
print(result.run_id, result.status)
```

---

## Structured output example

```python
from pydantic import BaseModel

class Decision(BaseModel):
    action: str
    confidence: float

@wf.step("classify")
def classify(ctx):
    decision = ctx.llm.parse(
        Decision,
        messages=[
            {
                "role": "user",
                "content": "Classify this ticket and return strict JSON.",
            }
        ],
    )
    ctx.set("decision", decision.model_dump())
    return "done"
```

replayt logs the request, response metadata, and validated structured output as explicit run events.

## Documentation map

Start here when you want the repo's major guides in one place:

- [Main README](README.md) — overview, quickstart, examples, and CLI reference
- [Docs index](docs/README.md) — consolidated documentation for schemas, demos, style notes, and architecture artifacts
- [Examples README](src/examples/README.md) — runnable workflows, approval patterns, and integration composition ideas

See [src/examples/README.md](src/examples/README.md) for a progressive tutorial set with 12 real-life workflows, from a two-step hello-world run to tool use, retries, approvals, and structured LLM output.

---

## Typed tool example

```python
from pydantic import BaseModel

class AddInput(BaseModel):
    a: int
    b: int

class AddOutput(BaseModel):
    total: int

@wf.step("compute")
def compute(ctx):
    @ctx.tools.register
    def add(payload: AddInput) -> AddOutput:
        return AddOutput(total=payload.a + payload.b)

    result = ctx.tools.call("add", {"payload": {"a": 2, "b": 3}})
    ctx.set("sum", result.total)
    return None
```

---

## Approval gate example

```python
@wf.step("review")
def review(ctx):
    if ctx.is_approved("publish"):
        return "done"
    if ctx.is_rejected("publish"):
        return "abort"
    ctx.request_approval("publish", summary="Publish this draft?")
```

Run it, then resume it later from the CLI:

```bash
replayt run examples.publishing_preflight:wf \
  --inputs-json '{"draft":"A draft that may need review."}'

replayt resume examples.publishing_preflight:wf <run_id> --approval publish
```

---

## YAML workflow example

The YAML mode is intentionally small. It is useful for straightforward deterministic flows, not for replacing Python as the primary authoring surface.

```yaml
name: refund-routing
version: 1
initial: ingest
steps:
  ingest:
    require: [ticket, route]
    set:
      stage: ingested
    next: branch

  branch:
    branch:
      key: route
      cases:
        refund: refund
        deny: deny
      default: deny

  refund:
    set:
      decision: refund

  deny:
    set:
      decision: deny
```

---

## Example workflows included

replayt ships with three example workflows that demonstrate the intended product shape:

- **GitHub issue triage** — validate issue shape, classify it, route or request more information
- **Refund policy workflow** — enforce constrained support outcomes with explicit actions
- **Publishing preflight** — check a draft, pause for approval, then finalize or abort

See [`src/examples/README.md`](src/examples/README.md) for runnable commands.

---

## CLI reference

### `replayt init [--path DIR] [--force]`
Write `workflow.py` and `.env.example`. Refuses to overwrite unless `--force`.

### `replayt run TARGET`
Run a workflow from a module reference, Python file, or YAML file. Flags: `--output text|json`, `--log-mode …`, `--resume`, `--tag key=value` (repeatable), `--timeout SECONDS`, etc. **Exit codes:** `0` completed, `1` failed, `2` paused.

### `replayt inspect RUN_ID`
Show a summary and event list for a run. `--output json` (or `--json`) prints `{"summary": …, "events": …}`.

### `replayt replay RUN_ID`
Show the recorded execution timeline without calling any model APIs. `--format html` emits a self-contained HTML page (Tailwind CDN); `--out PATH` writes to a file.

### `replayt resume TARGET RUN_ID --approval ID`
Resolve an approval gate and continue a paused run. Same exit codes as `run`.

### `replayt graph TARGET`
Print a Mermaid graph of the workflow.

### `replayt validate TARGET`
Validate a workflow graph without calling any LLM. Checks: initial state is set, all transition targets are declared states, no orphan states (unreachable from initial), all steps have handlers. Exit `0` if valid, `1` if not. Useful in CI.

### `replayt diff RUN_A RUN_B`
Compare two runs: states visited, structured outputs (field-by-field diff), tool calls, final status, and latency differences. `--output json` for machine-readable diff.

### `replayt gc --older-than DURATION`
Delete JSONL run logs older than a duration (e.g. `90d`, `24h`). `--dry-run` to preview. Prints a summary of files deleted and bytes freed.

### `replayt runs`
List recent local runs from the JSONL log directory. `--tag key=value` (repeatable) to filter by tags.

### `replayt stats [--days N] [--tag key=value] [--output text|json]`
Summarize local logs: status counts, average `llm_response` latency, token usage, top failure states, event time range. `--tag key=value` (repeatable) to filter by tags.

### `replayt doctor`
Check your local install, environment variables, optional YAML support, and default provider connectivity.

---

## Log model

Run events are append-only and local-first. A typical run log captures:

- workflow name and version
- run ID
- timestamps and event sequence numbers
- state entry and exit
- transition decisions
- LLM requests and responses
- validated structured outputs
- tool calls and results
- retries and failures
- approval requests and resolutions
- final status

See [`docs/RUN_LOG_SCHEMA.md`](docs/RUN_LOG_SCHEMA.md) for the event schema, [`docs/README.md`](docs/README.md) for the consolidated docs index, and [`src/examples/README.md`](src/examples/README.md) for the runnable workflow guide.

---

## Positioning

Good language for replayt:

- deterministic LLM workflows
- replayable LLM runs
- explicit state transitions
- schema-enforced steps
- local-first workflow runner
- inspectable AI pipelines
- approval-gated workflows
- typed LLM orchestration

Bad language for replayt:

- autonomous agents
- AI workforce
- agent operating system
- enterprise AI platform
- intelligent orchestration layer
- self-improving agents

The tone should be anti-hype and pro-discipline.

Browsing runs, building approval UIs, or wiring internal dashboards should treat **JSONL and SQLite files you own** as the source of truth. replayt remains the **engine**; your app owns auth, routing, and UX.

---

## When replayt is the right choice

Use replayt when:

- you want explicit control over workflow states
- you need strict schema validation around model outputs
- you care about local run history and replay
- you want approval gates to be explicit instead of ad hoc
- you distrust hidden control flow in production systems

Use something else when:

- you want autonomous long-running agents
- you need a distributed workflow engine with cross-process durability
- you want a visual graph builder
- you need a broad AI platform rather than a tiny runtime

---

## Running replayt as a bounded process

replayt is a **library and CLI for finite runs**, not a long-lived cluster orchestrator. In production-style setups:

- Prefer **one OS process (or container)** per run: invoke `replayt run …` or `Runner.run(...)` once, then exit.
- Alternatively, use a **queue worker** that dequeues a job, calls `Runner.run(..., run_id=…)` exactly once per message, then exits or acks—see **Pattern: queue worker** in [`src/examples/README.md`](src/examples/README.md).

Put **retries across jobs**, concurrency limits, and backpressure in your scheduler (Celery, Airflow, K8s Jobs, SQS consumers), not inside replayt core.

---

## Requests we will not take in core (and what to do instead)

replayt stays small on purpose. These are common asks that **do not belong in the core library**; compose them in **your** app or ops stack.

| You might ask for… | Why we avoid it in core | Do this instead |
| --- | --- | --- |
| **Hosted approval UI, multi-user queues, team RBAC** | That is a product surface, not a runtime primitive. | Build a tiny local **approval bridge**: read paused runs from JSONL/SQLite, render a UI, append `approval_resolved` (same event shape as `replayt resume`). See **Pattern: approval bridge** in [`src/examples/README.md`](src/examples/README.md). |
| **OpenTelemetry traces, metrics, fancy dashboards** | replayt is not an observability platform. | Treat JSONL as the **source of truth**; ship lines to Vector, Loki, Splunk, or S3 with your existing pipeline. Example Vector skeleton (conceptual): `source file` → `sink http`/`sink console`; point `include` at `.replayt/runs/*.jsonl`. |
| **Built-in RAG / memory / vector DB** | Scope creep into an “AI platform.” | Put retrieval **inside a typed tool** or a plain Python function your step calls; return a Pydantic model, log `tool_result`. |
| **LangChain / LangGraph / “agent framework” integration** | Hides control flow; competes with our explicit FSM story. | If you must: call that stack **inside one step’s handler**; keep transitions and approvals in replayt. Confine the framework to **one step** and normalize to **one** Pydantic exit shape before transitioning. Prefer **no** framework in the hot path. |
| **Multi-tenant isolation, enterprise secrets managers** | Deployment and policy vary per org. | **One tenant → one log directory** (or SQLite file): e.g. `.replayt/runs/customer_a/` on an **encrypted volume** if policy requires encryption at rest. Load secrets in your process wrapper or shell; export `OPENAI_API_KEY` before `replayt run`. Combine with `LogMode.redacted` or `structured_only` to limit sensitive payloads in logs (see examples README). |
| **Batch orchestration (Spark, Celery, Airflow as “the runner”)** | replayt is not a distributed engine. | **Outer loop** in your scheduler: for each row/job, `Runner.run(..., inputs=..., run_id=...)` with a unique `run_id`; use separate log dirs per job if needed. See **Pattern: batch driver** in examples README. |
| **Streaming tokens as first-class events** | Complicates replay semantics and event volume. | Stream inside your code if required; log **final** structured output (or a summary event you emit yourself in application code). Do **not** let the model silently rewrite the graph—changing control flow stays **human- or code-initiated** (`replayt resume`, explicit transitions, or a new run). |
| **Built-in eval suite (`replayt eval`), leaderboards, golden datasets** | replayt is a workflow runner, not an eval product (see *What replayt is not*). | Drive **`Runner.run`** from **pytest** (or any harness) with frozen inputs; assert on final context or `structured_output` events in JSONL; use **`replayt replay`** for human-readable postmortems. See **Pattern: golden path test** in [`src/examples/README.md`](src/examples/README.md). |
| **Warehouse-native sinks (Snowflake, BigQuery) and bundled dbt models** | replayt is not an observability or analytics platform. | Treat JSONL as the source of truth: **`duckdb` + `read_json_auto`**, **`jq`**, or your existing log shipper (see the Vector sketch in the OpenTelemetry row). See **Pattern: DuckDB ad-hoc analytics** in [`src/examples/README.md`](src/examples/README.md). |
| **Workflow plugin marketplace, dynamic `pip install` of steps at runtime** | **Tiny mental model** and explicit code imports; dynamic loading hides behavior. | Distribute shared workflows as **normal Python packages** (`from my_org_workflows import wf`); pin versions in `requirements.txt`. See **Pattern: reusable workflow package** in [`src/examples/README.md`](src/examples/README.md). |
| **Official Kubernetes operator, sidecar, or “always-on” replayt daemon** | replayt is not a distributed process engine. | Use **one Job Pod or task per run**, or a **queue worker** that calls `Runner.run` once per message (examples README). |
| **Guaranteed bitwise replay of LLM outputs across providers** | Not achievable in general. | Use **timeline replay** (`replayt replay`) for audit; for tests, **mock** the client or freeze fixtures; pin provider + model in metadata. |

For **per-call LLM settings** (model, temperature, `max_tokens`, timeout, extra headers) without a fork, use `ctx.llm.with_settings(...)` so overrides are explicit and show up under `effective` on `llm_request` events.

---

## Development

```bash
python -m build
pytest
ruff check src tests
```

A minimal CI job mirrors that: install with `pip install -e ".[dev]"`, run `pytest`, then `ruff check src tests`.

More detail lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).
