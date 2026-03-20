# Production checklist

How to run replayt safely in real environments: one finite run, logs you control, and clear exit semantics. For scope boundaries (“what we won’t add to core”), see [`SCOPE.md`](SCOPE.md).

## Process model

replayt is a **library and CLI for finite runs**, not a long-lived cluster orchestrator.

- Prefer **one OS process (or container)** per run: invoke `replayt run …` or `Runner.run(...)` once, then exit.
- Alternatively, use a **queue worker** that dequeues a job, calls `Runner.run(..., run_id=…)` exactly once per message, then exits or acks—see **Pattern: queue worker** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

Put **retries across jobs**, concurrency limits, and backpressure in your scheduler (Celery, Airflow, K8s Jobs, SQS consumers), not inside replayt core.

## Logs and sensitive data

- Default log directory is under `.replayt/runs/` (override with `--log-dir` or config—see [`CONFIG.md`](CONFIG.md)).
- Choose **`LogMode`** explicitly in Python (`LogMode.redacted`, `structured_only`, or full) or via CLI `--log-mode`. **Redacted** is a good default when prompts or payloads may contain PII; see [`RUN_LOG_SCHEMA.md`](RUN_LOG_SCHEMA.md) for what each event records.
- Optional **SQLite** mirror: same events; treat the files as **data you own** (backup, encryption at rest, retention).

## Human approvals

- Paused runs exit with status **`2`**. Resolve with `replayt resume TARGET RUN_ID --approval ID` (or `--reject`).
- For a web or Slack UI, use **Pattern: approval bridge** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md)—replayt stays the engine; your app owns auth and UX.

## CI and validation

- **`replayt validate TARGET`** — graph checks with no LLM calls ([`CLI.md`](CLI.md)).
- **Exit codes:** `0` completed, `1` failed, `2` paused (approval required).
- Prefer **mocked LLM** in automated tests; see [`RECIPES.md`](RECIPES.md) and **Pattern: golden path test** in [`EXAMPLES_PATTERNS.md`](EXAMPLES_PATTERNS.md).

## Multi-tenant / isolation

- **One tenant → one log directory** (or SQLite file), e.g. `.replayt/runs/customer_a/` on an encrypted volume if required. See the multi-tenant row in [`SCOPE.md`](SCOPE.md).

## Shareable artifacts

- `replayt replay RUN_ID --format html --out run.html` — self-contained timeline (Tailwind via CDN).
- `replayt report RUN_ID --out report.html` — summary report for reviews.

For Tailwind conventions when building your own UI, see [`STYLE.md`](STYLE.md).
