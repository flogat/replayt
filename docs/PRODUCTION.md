# Production checklist

How to run replayt safely in real environments: one finite run, logs you control, and clear exit semantics. For scope boundaries (“what we won’t add to core”), see [`SCOPE.md`](SCOPE.md).

## Process model

replayt is a **library and CLI for finite runs**, not a long-lived cluster orchestrator.

- Prefer **one OS process (or container)** per run: invoke `replayt run …` or `Runner.run(...)` once, then exit.
- Alternatively, use a **queue worker** that dequeues a job, calls `Runner.run(..., run_id=…)` exactly once per message, then exits or acks—see **Pattern: queue worker** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

Put **retries across jobs**, concurrency limits, and backpressure in your scheduler (Celery, Airflow, K8s Jobs, SQS consumers), not inside replayt core.

### Kubernetes Job (one run per Pod)

replayt is not a cluster operator; a **Job** that runs once and exits is the usual pattern. Mount a **PersistentVolumeClaim** (or use an object-store upload step after the Job finishes) for `.replayt` logs if you need retention across Pod restarts.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: replayt-once
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: replayt
          image: python:3.12-slim
          command: ["bash", "-lc"]
          args:
            - pip install replayt && replayt run your.module:wf --log-dir /data/runs --inputs-json '{}'
          env:
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef: { name: llm-secrets, key: OPENAI_API_KEY }
          volumeMounts:
            - name: runs
              mountPath: /data/runs
      volumes:
        - name: runs
          persistentVolumeClaim:
            claimName: replayt-runs-pvc
```

Preflight with `replayt doctor` in an init container or a separate CI job if you want connectivity checks without running the workflow.

## Logs and sensitive data

- Default log directory is under `.replayt/runs/` (override with `--log-dir` or config—see [`CONFIG.md`](CONFIG.md)).
- Choose **`LogMode`** explicitly in Python (`LogMode.redacted`, `structured_only`, or full) or via CLI `--log-mode`. **Redacted** is a good default when prompts or payloads may contain PII; see [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md) for what each event records.
- Optional **SQLite** mirror: same events; treat the files as **data you own** (backup, encryption at rest, retention).
- **SQLite mirror consistency:** With `strict_mirror = false` (default in some templates), a failed mirror write leaves the JSONL primary ahead of SQLite—mirror failures are logged at WARNING and the run continues. Set **`strict_mirror = true`** in project config when SQLite must match JSONL or the run should abort on mirror errors. See [`CONFIG.md`](CONFIG.md).
- **Disk permissions:** restrict who can read or write the log directory (same trust model as credential files). For shareable evidence packets, use `replayt export-run` / `replayt seal` and store artifacts on WORM media or signed archives if policy requires it—see README *Security and trust boundaries*.

## Human approvals

- Paused runs exit with status **`2`**. Resolve with `replayt resume TARGET RUN_ID --approval ID` (or `--reject`).
- For a web or Slack UI, use **Pattern: approval bridge** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md)—replayt stays the engine; your app owns auth and UX.

## CI and validation

- **`replayt validate TARGET`** — graph checks with no LLM calls ([`CLI.md`](CLI.md)).
- **Exit codes:** `0` completed, `1` failed, `2` paused (approval required).
- Prefer **mocked LLM** in automated tests; see [`RECIPES.md`](RECIPES.md) and **Pattern: golden path test** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

## LLM base URL (SSRF)

`OPENAI_BASE_URL` / `LLMSettings.base_url` must come from **trusted** configuration—never from untrusted user input. Pointing the runner at an arbitrary URL is effectively **server-side request forgery** from the process network position. Local gateways (Ollama, corporate proxies) are normal; unvalidated URLs are not.

## Multi-tenant / isolation

- **One tenant → one log directory** (or SQLite file), e.g. `.replayt/runs/customer_a/` on an encrypted volume if required. See the multi-tenant row in [`SCOPE.md`](SCOPE.md).

## Shareable artifacts

- `replayt replay RUN_ID --format html --out run.html` — self-contained timeline (Tailwind via CDN).
- `replayt report RUN_ID --out report.html` — summary report for reviews.

For Tailwind conventions when building your own UI, see [`STYLE.md`](STYLE.md).
