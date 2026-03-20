# Demo checklist

Product positioning, diagrams, and the full story live in the [**main README**](../README.md). This file is for **smoke tests**, **terminal recordings**, and **release** reminders.

## The three-step loop (reminder)

1. **`replayt run`** — run a workflow, get a run ID.
2. **`replayt inspect`** — summary and events.
3. **`replayt replay`** or **`replayt report`** — shareable HTML without calling the model again.

See also [Five-minute quickstart](QUICKSTART.md).

## One-liner smoke test

```bash
pip install -e ".[dev]"
replayt graph examples.issue_triage:wf
```

## Recording a live terminal demo (60–90 s)

Embed a cast in the README once published (asciinema or screen recording):

1. `replayt run examples.issue_triage:wf --inputs-json '{"issue":{"title":"Crash on save","body":"Steps: open, save, crash."}}'`
2. `replayt inspect <run_id>` then `replayt replay <run_id>` (or `replayt report <run_id> --out report.html`)
3. For approvals: run the publishing example, let it pause, then `replayt resume ... --approval publish` followed by `replayt replay`

Use [asciinema](https://asciinema.org/) or any screen recorder; link the cast from the main README when ready.

## PyPI publish

Publishing is automated — see the **Releasing a new version** section in [CONTRIBUTING.md](../CONTRIBUTING.md).
