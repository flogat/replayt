# Examples

These examples are meant to show what replayt is good at:

- concrete workflows
- explicit branching
- strict outputs
- local replay
- realistic approval gates

Install locally first:

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
```

## A. GitHub issue triage

A relatable developer workflow with deterministic routing.

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

Then inspect what happened:

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

## B. Refund policy workflow

A constrained support decision flow where the output space stays narrow and auditable.

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"Customer says package never arrived","order":{"order_id":"A-1","amount_cents":4999,"delivered":false,"days_since_delivery":0}}'
```

## C. Publishing preflight with approval gate

A workflow that pauses for a human decision before continuing.

```bash
replayt run examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
```

Approve it:

```bash
replayt resume examples.publishing_preflight:wf <run_id> --approval publish
```

Reject it instead:

```bash
replayt resume examples.publishing_preflight:wf <run_id> --approval publish --reject
```

## D. Python file target

replayt can load a workflow directly from a Python file if it exports `wf` or `workflow`.

```bash
replayt run workflow.py --inputs-json '{"ticket":"hello"}'
```

## E. YAML workflow target

For small declarative flows, replayt can run a workflow directly from YAML.

```bash
replayt run workflow.yaml --inputs-json '{"route":"refund","ticket":"where is my order?"}'
```

## F. Graph export

```bash
replayt graph examples.issue_triage:wf
```
