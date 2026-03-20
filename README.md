# replayt

> **Deterministic control flow for LLM workflows you can replay.**

<p align="center">
  <img src="docs/demo.svg" alt="replayt demo: run, inspect, replay" width="820"/>
</p>

**replayt** is a tiny Python library and CLI for developers who want to use LLMs in real workflows **without** adopting a sprawling agent framework, hosted platform, no-code builder, or “AI operating system.”

**Where it fits**

| Topic | **Plain Python** (`if` / `else`, ad hoc logging) | **Agent / planner stacks** | **replayt** |
| --- | --- | --- | --- |
| **Control flow** | Fully explicit, but you reinvent structure each time | Often implicit or planner-driven | **Explicit** states and transitions in code |
| **Audit trail** | Whatever you print | Often uneven | **Append-only JSONL** (and optional SQLite) with a stable event schema |
| **Human gates** | Custom | Often bolted on | **First-class** pause / resume with exit code `2` |
| **Tradeoff** | No conventions | Harder to answer “what happened?” | You model a **finite run**—not a distributed workflow engine |

The core idea is simple:

> If a workflow matters, it should be explicit, inspectable, and replayable.

Transitions and branching are **your code**; the model does not silently rewrite the graph. Structured outputs are **validated** (Pydantic) and **logged**. **Timeline replay** (`replayt replay`, `replayt report`) walks the **recorded** history without calling the provider again—it is not a promise of bitwise-identical regeneration from the API (see [docs/SCOPE.md](docs/SCOPE.md)).

**Start here:** [Five-minute quickstart](docs/QUICKSTART.md) · [Progressive tutorial & patterns](src/examples/README.md)

**Terminal demo:** Record a short walkthrough with [docs/DEMO.md](docs/DEMO.md) (asciinema or screen capture); embed or link the cast from the README when published.

**Three commands** once installed:

```bash
replayt run examples.e01_hello_world:wf --inputs-json '{"customer_name":"Sam"}'
replayt inspect <run_id>
replayt replay <run_id>
```

That is the whole loop; everything else is detail.

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

<p align="center">
  <img src="docs/demo-why.svg" alt="typical agent framework vs replayt" width="820"/>
</p>

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

The goal is that you can always explain what happened and why.

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

replayt stays small enough to understand in one sitting.

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

When things go wrong, the run log is the debugging tool:

<p align="center">
  <img src="docs/demo-debug.svg" alt="replayt debugging a failed run" width="820"/>
</p>

### CLI

- `replayt init` — scaffold `workflow.py` + `.env.example`
- `replayt run TARGET` — `--output json` for machine-readable result; `--tag key=value`; `--timeout SECONDS`; exit **0** completed, **1** failed, **2** paused
- `replayt inspect RUN_ID` — `--output json` (or legacy `--json`) for summary + events
- `replayt replay RUN_ID` — `--format html` for a shareable Tailwind HTML timeline (`--out path`)
- `replayt report RUN_ID` — self-contained HTML report; `--out path` or stdout
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
pip install replayt
# pip install replayt[yaml]  # if you run .yaml / .yml workflow targets
# pip install -e ".[dev]"     # from a clone: tests, ruff, PyYAML for contributors
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
pip install replayt
# pip install replayt[yaml]  # YAML workflow targets
# pip install -e ".[dev]"    # from a clone: contributors
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
replayt report <run_id> --out report.html   # self-contained HTML summary
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

- [Five-minute quickstart](docs/QUICKSTART.md) — install, first run, annotated JSONL sample
- [Main README](README.md) — overview, quickstart, examples, and CLI reference
- [Scope / non-goals (long)](docs/SCOPE.md) — what will not land in core and recommended composition patterns
- [Docs index](docs/README.md) — schemas, demos, style notes, architecture artifacts
- [Examples README](src/examples/README.md) — progressive tutorial (14 runnable workflows), approval patterns, integration ideas

See [src/examples/README.md](src/examples/README.md) for the full tutorial path—from a two-step hello world through tools, retries, approvals, structured LLM output, YAML, and SDK integration examples.

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

<p align="center">
  <img src="docs/demo-approval.svg" alt="replayt approval gate: pause, review, resume" width="820"/>
</p>

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

The repo ships a **progressive tutorial** of **14 runnable workflows** (deterministic steps, LLM-backed classification, tools, retries, approvals, YAML, OpenAI/Anthropic SDK patterns)—see [`src/examples/README.md`](src/examples/README.md).

**Featured narratives** (good first reads in the tutorial):

- **GitHub issue triage** — validate issue shape, classify it, route or request more information
- **Refund policy** — constrained support decisions with structured model output
- **Publishing preflight** — checklist + pause for approval, then finalize or abort

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

### `replayt report RUN_ID`
Generate a self-contained HTML report for a run (summary, states, structured outputs, tool calls). `--out PATH` writes to a file; omit `--out` to print to stdout. Uses `--log-dir` / `--sqlite` like other read-only commands.

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

replayt stays small on purpose. The full table of common asks, rationale, and **composition patterns** (approval bridge, batch driver, golden tests, etc.) lives in **[docs/SCOPE.md](docs/SCOPE.md)** so this README stays easier to scan.

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
