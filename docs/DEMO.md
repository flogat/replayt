# Demo

## Animated terminal walkthrough

The SVG below shows the three-step replayt loop: **run → inspect → replay**.

<p align="center">
  <img src="demo.svg" alt="replayt demo: run, inspect, replay" width="820"/>
</p>

The flow:

1. **`replayt run`** — execute a workflow, get a run ID and summary.
2. **`replayt inspect`** — see the full event log for that run (states, LLM calls, tool calls).
3. **`replayt replay`** — walk the recorded timeline step by step, no LLM calls needed.

Every step is logged. Every step is replayable. That's the entire pitch.

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
