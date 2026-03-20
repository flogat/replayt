# Five-minute quickstart

This page is the shortest path from zero to **run → inspect → understand the log**. For a full progressive tutorial (many workflows, patterns, and integrations), use [`src/examples/README.md`](../src/examples/README.md).

## 1. Install

**End users (PyPI):**

```bash
python -m venv .venv && source .venv/bin/activate  # or Windows equivalent
pip install replayt
# pip install replayt[yaml]   # if you run .yaml / .yml workflow files
replayt doctor
```

**From a clone (contributors):**

```bash
pip install -e ".[dev]"
replayt doctor
```

## 2. Run a workflow (no API key needed)

The hello-world example is deterministic—no LLM:

```bash
replayt run examples.e01_hello_world:wf \
  --inputs-json '{"customer_name":"Sam"}'
```

Note the printed **run ID** (UUID).

## 3. Inspect and replay

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

Share a static HTML timeline (Tailwind via CDN):

```bash
replayt replay <run_id> --format html --out run.html
```

Or a self-contained report:

```bash
replayt report <run_id> --out report.html
```

## 4. Annotated run log (what “inspectable” means)

Each run is an append-only **JSONL** file under `.replayt/runs/` (one line per event). Shapes are defined in [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md). Below is a **trimmed excerpt** from `examples.e01_hello_world` (line breaks added for reading; on disk each event is one line).

```jsonl
{"ts": "2026-03-20T19:22:59.181461+00:00", "run_id": "…", "seq": 1, "type": "run_started", "payload": {"workflow_name": "hello_world_tutorial", "workflow_version": "1", "initial_state": "greet", "inputs": {"customer_name": "Sam"}}}
{"ts": "…", "run_id": "…", "seq": 2, "type": "state_entered", "payload": {"state": "greet"}}
{"ts": "…", "run_id": "…", "seq": 3, "type": "state_exited", "payload": {"state": "greet", "next_state": "done"}}
{"ts": "…", "run_id": "…", "seq": 4, "type": "transition", "payload": {"from_state": "greet", "to_state": "done", "reason": ""}}
{"ts": "…", "run_id": "…", "seq": 5, "type": "state_entered", "payload": {"state": "done"}}
{"ts": "…", "run_id": "…", "seq": 6, "type": "state_exited", "payload": {"state": "done", "next_state": null}}
{"ts": "…", "run_id": "…", "seq": 7, "type": "run_completed", "payload": {"final_state": "done", "status": "completed"}}
```

| Event | What it tells you |
|-------|-------------------|
| `run_started` | Which workflow/version ran, initial state, and inputs (may be redacted depending on log mode). |
| `state_entered` / `state_exited` | **When** each handler ran and **which** next state it returned. |
| `transition` | Explicit edge in the graph (good for diffs and audits). `reason` may be empty. |
| `next_state: null` on exit | Terminal state—no further steps. |
| `run_completed` | Final status (`completed`, `failed`, etc.). |

Workflows that call an LLM add `llm_request`, `llm_response`, and `structured_output` events; tool usage adds `tool_call` / `tool_result`; approvals add `approval_requested` / `approval_resolved`. Same file—same mental model.

## 5. Where replayt fits (one glance)

| Approach | You get… | Tradeoff |
|----------|----------|----------|
| **Plain Python** (`if`/`else`, your own prints) | Full flexibility | Ad hoc logs; hard to standardize replay, approvals, and CI. |
| **Agent / planner frameworks** | Fast demos | Hidden control flow; “what happened?” is often unclear. |
| **replayt** | Explicit FSM + **schema-shaped** outputs + **local JSONL** + CLI (`inspect`, `replay`, `report`) | You write states and transitions; not a distributed workflow engine. |

## Next steps

- LLM-backed examples: [`src/examples/README.md`](../src/examples/README.md) (start at section 6+ or jump to **issue triage**).
- Event schema reference: [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md).
- Scope / non-goals in depth: [`SCOPE.md`](SCOPE.md).
