# Examples

Install editable so `examples.*` imports resolve:

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
```

### A — GitHub issue triage

```bash
replayt run examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, it throws. v1.2."}}'
```

### B — Support refund policy

```bash
replayt run examples.refund_policy:wf \
  --inputs-json '{"ticket":"Customer says package never arrived","order":{"order_id":"A-1","amount_cents":4999,"delivered":false,"days_since_delivery":0}}'
```

### C — Publishing preflight + approval gate

```bash
replayt run examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
# copy run_id from output, then:
replayt resume examples.publishing_preflight:wf "<run_id>" --approval publish
replayt replay "<run_id>"
```

Reject instead of approve:

```bash
replayt resume examples.publishing_preflight:wf "<run_id>" --approval publish --reject
```

### Graph export

```bash
replayt graph examples.issue_triage:wf
```
