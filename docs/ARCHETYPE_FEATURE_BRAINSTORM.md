## Archetype feature brainstorm (10)

These ideas stay inside replayt's contract: explicit states, strict schemas, typed tools, local-first logs, and replay as a first-class artifact. The deferred items below already have user-facing "do this outside core" guidance in the existing docs, so the documentation follow-up is satisfied in this pass without another README or tutorial edit.

### 1. Staff engineer / platform - Workflow policy profile
- **Request:** Add a checked-in workflow policy profile so `replayt validate` can fail when a workflow drifts from repo standards such as required transition declarations, allowed log modes, mandatory approval ids, or pinned `llm_defaults`, giving platform teams one explicit policy surface instead of ad hoc review comments.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 2. Junior dev onboarding - Copy-paste debug packet
- **Request:** Add `replayt doctor --starter` to print the exact next commands for the current shell, a tiny `workflow.py`, and one sample `--inputs-json` block so a new user can go from install to `replayt replay` without guessing activation syntax, import targets, or where logs land.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 3. Security / compliance - Seal verification and chain summary
- **Request:** Add `replayt verify-seal RUN_ID` to confirm the current JSONL still matches the SHA-256 manifest from `replayt seal`, print which files changed, and emit a machine-readable status for audit pipelines that archive or hand off run logs.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 4. ML / LLM engineer - Prompt and provider sweep harness
- **Request:** Add `replayt sweep TARGET --variant prompt_a --variant prompt_b --provider openai --provider openrouter` so one command can fan a workflow across prompts and `ctx.llm.with_settings(...)` variants, score the outputs, and rank the runs inside replayt.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This pulls replayt toward an eval product instead of a small `Runner`, which conflicts with **Small mental model** and the **Built-in eval suite (`replayt eval`), leaderboards, golden datasets** row in [`docs/SCOPE.md`](./SCOPE.md).
- **Suggested overcome:** Keep the sweep outside core: drive `Runner.run(...)` from pytest or a plain loop, tag runs with `experiment={...}` through `ctx.llm.with_settings(...)`, and compare final context or `structured_output` events in JSONL. The user-facing path already exists in [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks**, plus **Pattern: golden path test (pytest)** and **Pattern: batch driver (Airflow / Celery / plain loop)** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md).

### 5. DevOps / SRE - Machine-readable paused-run inventory
- **Request:** Add `replayt approvals --pending --format json` and `replayt runs --status paused --older-than 30m` so queue workers, cron jobs, and CI wrappers can detect stuck approvals and stale finite runs without re-parsing raw JSONL files.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 6. Product engineer - Approval handoff packet
- **Request:** Add `replayt report RUN_ID --style approver --out approval.html` that centers the latest structured output, relevant tool results, approval summary, and exact `replayt resume ... --approval ...` commands so a reviewer gets one local packet instead of reading the whole event stream.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 7. Open-source maintainer - Example command verifier
- **Request:** Add a maintainer check that extracts runnable CLI lines from README and tutorial docs, executes the import-target validation parts in CI, and flags stale example targets before release notes or PyPI docs drift away from the shipped examples.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 8. "Just ship it" startup IC - Starter templates for common flows
- **Request:** Extend `replayt init` with small named templates such as `classify-route`, `approval-review`, and `tool-check` so a team can stamp out a real explicit-state workflow with one command, then edit the handlers instead of wiring `Runner`, JSONL storage, and log mode from scratch.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 9. Enterprise integrator - Typed resume-hook contract
- **Request:** Formalize the `resume_hook` payload and result schema, add `replayt resume --dry-hook`, and ship a documented `ApprovalActor` envelope so policy gateways can stamp ticket ids, group claims, and decision metadata into `approval_resolved` without inventing incompatible blobs per repo.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 10. Framework enthusiast - Hosted planner bridge inside Runner
- **Request:** Teach `Runner` to host LangGraph-style planners, emit per-token stream events into JSONL, and let framework subgraphs decide replayt transitions directly instead of forcing those systems into one explicit step.
- **Aligns with principles:** no
- **Scope:** compose outside core
- **Principle / scope tension:** This conflicts with **Determinism over autonomy**, **Explicit states over hidden loops**, and the **LangChain / LangGraph / "agent framework" integration** row in [`docs/SCOPE.md`](./SCOPE.md); framework-owned subgraphs would hide control flow and flood the replay log.
- **Suggested overcome:** Keep the framework inside one replayt step, stream there if needed, normalize to one Pydantic exit shape, and choose the next state explicitly in Python. The user-facing path already exists in [`README.md`](../README.md) under **Streaming, planner loops, and "agents" (composition, not core)**, in [`src/replayt_examples/README.md`](../src/replayt_examples/README.md) under **Framework-style agents, streaming, and planner loops (feature 10 / composition)** and **LangGraph (and similar frameworks): composition, not core**, and in **Pattern: framework in a sandbox step** plus **Pattern: stream inside step, log structured summary** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md).

## Summary table

| # | Archetype | Feature | Aligns | Scope |
|---|-----------|---------|--------|-------|
| 1 | Staff engineer / platform | Workflow policy profile | yes | in-core candidate |
| 2 | Junior dev onboarding | Copy-paste debug packet | yes | in-core candidate |
| 3 | Security / compliance | Seal verification and chain summary | yes | in-core candidate |
| 4 | ML / LLM engineer | Prompt and provider sweep harness | partial | compose outside core |
| 5 | DevOps / SRE | Machine-readable paused-run inventory | yes | in-core candidate |
| 6 | Product engineer | Approval handoff packet | yes | in-core candidate |
| 7 | Open-source maintainer | Example command verifier | yes | in-core candidate |
| 8 | "Just ship it" startup IC | Starter templates for common flows | yes | in-core candidate |
| 9 | Enterprise integrator | Typed resume-hook contract | yes | in-core candidate |
| 10 | Framework enthusiast | Hosted planner bridge inside Runner | no | compose outside core |
