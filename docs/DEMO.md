# Demo

## The three-step loop: run, inspect, replay

Every replayt session follows the same pattern. Run a workflow, inspect what happened, replay the full timeline offline.

<p align="center">
  <img src="demo.svg" alt="replayt demo: run, inspect, replay" width="820"/>
</p>

1. **`replayt run`** — run a workflow, get a run ID and summary.
2. **`replayt inspect`** — see the full event log (states, LLM calls, tool calls).
3. **`replayt replay`** — walk the recorded timeline step by step, no LLM calls needed.

Every step is logged. Every step is replayable. That's the entire pitch.

---

## Why replayt — and where other approaches fall short

Most LLM tooling hides what actually happens behind agent planners, silent retries, and opaque sub-agent calls. When something goes wrong — or when you just need to understand what happened — you're stuck.

replayt goes in the opposite direction: explicit states, explicit transitions, full local logs.

<p align="center">
  <img src="demo-why.svg" alt="typical agent framework vs replayt" width="820"/>
</p>

| Typical agent framework | replayt |
|---|---|
| Hidden planner decides control flow | You define explicit states and transitions |
| Silent retry loops | Every retry recorded as an event |
| Sub-agents you can't inspect | One flat, auditable event log |
| Fuzzy text outputs | Pydantic-validated structured schemas |
| No approval story | First-class approval gates with pause/resume |
| "What happened?" — nobody knows | `replayt inspect` — every step, every time |

---

## Approval gates that actually work

Most frameworks treat human approvals as an afterthought — a webhook here, a polling hack there. In replayt, approvals are part of the workflow graph. The run pauses cleanly (exit code 2), persists to disk, and resumes whenever a human is ready.

<p align="center">
  <img src="demo-approval.svg" alt="replayt approval gate flow" width="820"/>
</p>

The flow:

1. **`replayt run`** — workflow hits an approval gate, pauses. Exit code 2.
2. **`replayt resume ... --approval publish`** — human approves, workflow completes.
3. The paused run persists in JSONL. Resume minutes or days later.
4. Inspect and replay show the approval event alongside every other step.

This is how approval-gated content pipelines, publishing workflows, and sensitive operations should work: the human decision is part of the auditable run history, not a side-channel.

---

## When things go wrong — debugging a failed run

With black-box agents, a failure means "error" and a shrug. With replayt, the full history is already on disk before the error message even prints. You can pinpoint exactly which state failed, what the LLM returned, and why validation rejected it.

<p align="center">
  <img src="demo-debug.svg" alt="replayt debugging a failed run" width="820"/>
</p>

The flow:

1. **`replayt run`** — workflow fails. Exit code 1. But the run log is already saved.
2. **`replayt inspect`** — summary shows exactly how many events fired before the failure.
3. **`replayt replay`** — walks the timeline to the exact failure point, with the full error payload.

The run history is your debugging tool.

---

## One-liner smoke test

```bash
pip install -e ".[dev]"
replayt graph examples.issue_triage:wf
```

## Recording a live terminal demo (60–90 s)

For a live recording with real LLM calls, use [asciinema](https://asciinema.org/) or a screen recorder:

1. `replayt run examples.issue_triage:wf --inputs-json '{"issue":{"title":"Crash on save","body":"Steps: open, save, crash."}}'`
2. `replayt inspect <run_id>` then `replayt replay <run_id>`
3. For approvals: run the publishing example, let it pause, then `replayt resume ... --approval publish` followed by `replayt replay`

## PyPI publish

Publishing is automated — see the **Releasing a new version** section in [CONTRIBUTING.md](../CONTRIBUTING.md).
