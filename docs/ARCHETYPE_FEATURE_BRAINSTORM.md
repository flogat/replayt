## Archetype feature brainstorm (10)

These ideas stay grounded in replayt's current contract: explicit states, typed tools, strict schemas, local JSONL or SQLite history, and composition instead of product sprawl. Deferred items cite existing user-facing headings that already explain the supported "do this in your stack" path, so the documentation follow-up is satisfied without adding another README or tutorial subsection in this pass.

### 1. Staff engineer / platform - Frozen workflow contract diff
- **Request:** Add a `replayt contract` command (or `replayt validate --freeze-contract`) that emits a canonical JSON manifest for workflow name/version, declared states, noted transitions, expected input schema names, and logged `llm_defaults`, then fails CI when a checked-in contract drifts unexpectedly.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 2. Junior dev onboarding - Failure messages with next-command fixes
- **Request:** When `replayt doctor`, `run`, or `validate` fails for common setup mistakes, print one copy-pasteable fix plus the next command to run, such as missing `OPENAI_API_KEY`, a bad `module:wf` target, or a missing YAML extra.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 3. Security / compliance - Share-safe export preview
- **Request:** Add `replayt export-run --preview` so operators can see which event fields, context paths, and attachments would survive redaction, sealing, or bundle export before they hand a run to another team.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 4. ML / LLM engineer - Built-in prompt and provider matrix
- **Request:** Add a first-class `replayt eval` surface that sweeps prompts, providers, temperatures, and datasets, then scores or ranks runs as a built-in experiment harness.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This lands in the **Built-in eval suite (`replayt eval`), leaderboards, golden datasets** row in [`docs/SCOPE.md`](./SCOPE.md) and stretches the **Tiny mental model** from workflow runner into experiment platform territory.
- **Suggested overcome:** Keep the sweep outside core: drive `Runner.run` from pytest or a plain loop, tag runs with `ctx.llm.with_settings(experiment={...})`, and assert on final context or `structured_output` events in JSONL. The existing subsection [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks** plus **Pattern: golden path test (pytest)** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md) already documents the supported shape.

### 5. DevOps / SRE - Stale paused-run sweeper
- **Request:** Add a machine-readable `replayt approvals --stale 24h --format json` view so cron jobs and queue workers can flag paused runs, missing resume activity, or approval bottlenecks without building a separate parser first.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 6. Product engineer - Approval decision packet
- **Request:** Add a `replayt report --approval-packet` mode that turns a paused run into a compact HTML or Markdown handoff with the current state, approval summary, latest structured output, and exact approve or reject commands for a human reviewer.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 7. Open-source maintainer - Docs drift gate
- **Request:** Add a repo check that verifies tutorial `module:wf` targets still import, README headings referenced from other docs still exist, and common CLI snippets still parse, so releases do not quietly ship broken guidance.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 8. "Just ship it" startup IC - Vendored starter example
- **Request:** Add a shortcut such as `replayt try --write-example issue_triage` or `replayt init --preset support` that copies one working workflow, sample inputs, and a minimal `replayt ci` path into the caller's repo so a single engineer can demo the full loop fast.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 9. Enterprise integrator - Signed approval envelopes
- **Request:** Require `replayt resume` to accept externally signed identity and policy payloads so enterprise brokers can attach SSO claims, ticket ids, and approver attestations before a paused run continues.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This pushes replayt toward hosted approval workflow, RBAC, and tenant-specific policy logic, which conflicts with **Local-first by default**, **Tiny mental model**, and the **Hosted approval UI, multi-user queues, team RBAC** row in [`docs/SCOPE.md`](./SCOPE.md).
- **Suggested overcome:** Keep identity and signing in your broker, then resume the local run with `replayt resume --reason ... --actor-json ...` plus an optional `resume_hook` for policy logging or enforcement. The existing subsection [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks** plus **Pattern: approval bridge (local UI)** and **Pattern: webhook / lifecycle callbacks** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md) already shows the supported split.

### 10. Framework enthusiast - Dynamic subgraphs inside Runner
- **Request:** Embed LangGraph-style planners, streaming token events, and dynamic sub-agents directly in `Runner` so replayt can host a framework-managed graph instead of just wrapping one step.
- **Aligns with principles:** no
- **Scope:** compose outside core
- **Principle / scope tension:** This conflicts with **Determinism over autonomy**, **Explicit states over hidden loops**, and the **LangChain / LangGraph / "agent framework" integration** row in [`docs/SCOPE.md`](./SCOPE.md); planner-managed subgraphs would bury the explicit replay log.
- **Suggested overcome:** Keep the framework inside one replayt step, validate one exit shape, and return an explicit next state yourself. The existing subsections [`README.md`](../README.md) under **Streaming, planner loops, and "agents" (composition, not core)** and [`src/replayt_examples/README.md`](../src/replayt_examples/README.md) under **LangGraph (and similar frameworks) - composition, not core**, plus **Pattern: framework in a sandbox step** and **Pattern: stream inside step, log structured summary** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md), already cover the recommended composition pattern.

## Summary table

| # | Archetype | Feature | Aligns | Scope |
|---|-----------|---------|--------|-------|
| 1 | Staff engineer / platform | Frozen workflow contract diff | yes | in-core candidate |
| 2 | Junior dev onboarding | Failure messages with next-command fixes | yes | in-core candidate |
| 3 | Security / compliance | Share-safe export preview | yes | in-core candidate |
| 4 | ML / LLM engineer | Built-in prompt and provider matrix | partial | compose outside core |
| 5 | DevOps / SRE | Stale paused-run sweeper | yes | in-core candidate |
| 6 | Product engineer | Approval decision packet | yes | in-core candidate |
| 7 | Open-source maintainer | Docs drift gate | yes | in-core candidate |
| 8 | "Just ship it" startup IC | Vendored starter example | yes | in-core candidate |
| 9 | Enterprise integrator | Signed approval envelopes | partial | compose outside core |
| 10 | Framework enthusiast | Dynamic subgraphs inside Runner | no | compose outside core |
