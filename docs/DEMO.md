# Demo checklist

The [**README**](../README.md) has the overview and diagrams. This file is for **smoke tests**, **terminal recordings**, and **release** reminders.

## The three-step loop (reminder)

1. **`replayt run`**: run a workflow and get a run ID.
2. **`replayt inspect`**: review the summary and events.
3. **`replayt replay`** or **`replayt report`**: generate a shareable view without calling the model again.

See also [Five-minute quickstart](QUICKSTART.md).

## Asciinema cast

The repo includes a **short demo cast** (synthetic output): [`replayt-demo.cast`](replayt-demo.cast).

```bash
# pip install asciinema  OR: npx asciinema-terminal  (tooling varies by platform)
asciinema play docs/replayt-demo.cast
```

To record a **real** cast from your machine:

1. `replayt graph replayt_examples.issue_triage:wf`
2. `replayt run replayt_examples.issue_triage:wf --inputs-json '{"issue":{"title":"Crash on save","body":"Steps: open, save, crash."}}'`
3. `replayt inspect <run_id>` then `replayt replay <run_id>` (or `replayt report <run_id> --out report.html`)
4. Approvals: run the publishing example until it pauses, then `replayt resume ... --approval publish` and `replayt replay`

Record with [asciinema](https://asciinema.org/) or any screen recorder. Upload to asciinema.org and add the player link or raw cast URL to the main README if you want an embed.

## Smoke test

```bash
pip install -e ".[dev]"
replayt graph replayt_examples.issue_triage:wf
```

## PyPI publish

Publishing is automated. See the **Releasing a new version** section in [CONTRIBUTING.md](../CONTRIBUTING.md).
