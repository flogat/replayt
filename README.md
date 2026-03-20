# replayt

**Deterministic LLM workflows you can replay.** A small Python library and CLI: explicit steps, Pydantic-shaped outputs, typed tools, human approval checkpoints, and local JSONL/SQLite run logs.

If you can’t replay it, you can’t trust it.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
export OPENAI_API_KEY=...  # optional for LLM-free tests; required for examples that call models

replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Steps: open app, click save, boom. Expected: file writes."}}'
replayt inspect <run_id>
replayt replay <run_id>
```

## Why replayt exists

Agent frameworks optimize for open-ended autonomy. **replayt** optimizes for **boring reliability**: finite steps, strict schemas, inspectable runs, and local-first logs you can diff and archive.

## Design principles

1. **One-screen mental model** — small core, no hidden agent loops.
2. **Local-first** — no account, no hosted dependency in v1.
3. **Strictness over magic** — Pydantic validation and explicit transitions.
4. **Inspectability is the product** — JSONL/SQLite events are part of the default path.
5. **Tiny scope** — if it turns into a platform, something went wrong.

See [docs/RUN_LOG_SCHEMA.md](docs/RUN_LOG_SCHEMA.md) for the event model.

## Non-goals

- Multi-agent orchestration frameworks  
- Visual / no-code builders  
- Hosted SaaS, team RBAC, or enterprise governance in v1  
- A memory/RAG platform, eval suite, or “Temporal for everything”  
- Competing on feature breadth with LangGraph / PydanticAI / Mastra  

## When not to use replayt

- You want **long-running autonomous agents** with emergent tool choice and implicit looping: use an agent framework instead.  
- You need **distributed workflow durability** across processes: use a real workflow engine.  
- You want **deep graph editing / cyclic DAG UX**: replayt is closer to an explicit step machine with Python in the middle.  

## vs LangGraph / PydanticAI (charitable)

- **LangGraph** shines for **stateful graphs**, checkpoints, LangChain ecosystem integration, and long-horizon agents. replayt is intentionally smaller: fewer concepts, no graph runtime, explicit Python steps first.  
- **PydanticAI** is excellent for **typed agents** and model integration with strong ergonomics. replayt is narrower: **FSM-shaped workflows**, local replay logs, and CLI inspection as the headline.  

Pick replayt when the win is **auditability and restraint**, not when you need maximum expressiveness.

## Python API sketch

```python
from replayt import Workflow, Runner, LogMode
from replayt.persistence import JSONLStore
from pathlib import Path

wf = Workflow("demo")
wf.set_initial("hello")

@wf.step("hello")
def hello(ctx):
    ctx.set("msg", "replayt")
    return None  # end run

runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
result = runner.run(inputs={"demo": True})
print(result.run_id, result.status)
```

## CLI

- `replayt run MODULE:VAR` — execute a `Workflow` instance from any installed module.  
- `replayt inspect RUN_ID` — print event types; `--json` for raw log.  
- `replayt replay RUN_ID` — human timeline from recorded events (**no API calls**).  
- `replayt resume MODULE:VAR RUN_ID --approval ID` — append an approval resolution and continue paused runs.  
- `replayt graph MODULE:VAR` — print an optional Mermaid diagram (`Workflow.note_transition` helps when steps aren’t static).  

## Examples

See [src/examples/README.md](src/examples/README.md) for runnable issue triage, refund policy, and publishing preflight flows.

## Optional YAML spec

`pip install replayt[yaml]` — minimal declarative scaffolding lives in `replayt.yaml_workflow` (handlers are still Python today).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).

## Trademark

The **replayt** name is a project brand; it is not a guarantee of exclusive rights in all jurisdictions. Apache-2.0 governs the code only.
