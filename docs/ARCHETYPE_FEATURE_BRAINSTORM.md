## Archetype feature brainstorm (10)

These ideas stay grounded in replayt's current contract: explicit states, typed tools, strict schemas, local JSONL or SQLite history, and composition instead of product sprawl. Deferred items cite existing user-facing headings that already explain the supported "do this in your stack" path, so the documentation follow-up is satisfied without adding another README section in this pass.

### 1. Staff engineer / platform - Workflow compatibility profile
- **Request:** Add `replayt validate --profile stable` so teams can enforce declared transitions, workflow version metadata, import-target deprecation warnings, and a small compatibility manifest for published `module:wf` entrypoints.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 2. Junior dev onboarding - First-run scaffold with replay path
- **Request:** Extend `replayt init` to emit one tiny starter workflow, sample `inputs.json`, `.env` notes, and the exact next commands for `replayt doctor`, `replayt run --dry-check`, `replayt inspect`, and `replayt replay`.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 3. Security / compliance - Auditable log-policy manifest
- **Request:** Let operators attach a named log policy to each run and emit a manifest that records `LogMode`, masked field paths, seal status, export provenance, and whether structured-only or redacted storage was used.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 4. ML / LLM engineer - Eval matrix runner
- **Request:** Add a built-in `replayt eval` command that sweeps prompts, providers, temperatures, and sample datasets, then ranks outcomes and writes benchmark summaries as a first-class replayt product surface.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This drifts into the **Built-in eval suite (`replayt eval`), leaderboards, golden datasets** row in [`docs/SCOPE.md`](./SCOPE.md) and stretches **Tiny mental model** beyond a workflow runner.
- **Suggested overcome:** Keep the harness outside core: drive `Runner.run` from pytest or a plain loop, tag per-call settings with `ctx.llm.with_settings(experiment={...})`, and assert on final context or `structured_output` events. The existing subsection [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks** plus **Pattern: golden path test (pytest)** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md) already documents the supported shape.

### 5. DevOps / SRE - Container readiness doctor
- **Request:** Add `replayt doctor --ci` checks for writable log directories, SQLite mirror availability, `resume_hook` executability, expected env vars, and machine-readable failure output that works in containers and queue workers.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 6. Product engineer - Local approval inbox snapshot
- **Request:** Add a local `replayt approvals` summary that scans JSONL or SQLite for paused runs and prints a compact queue of approval ids, summaries, current state, timestamps, and resume commands that can be pasted into tickets or Slack threads.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 7. Open-source maintainer - Workflow package manifest
- **Request:** Define a lightweight manifest for reusable workflow packages so maintainers can publish stable import targets, minimum replayt version, example commands, and deprecation notices without inventing dynamic plugin loading.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 8. "Just ship it" startup IC - Bootstrap happy path
- **Request:** Ship a `replayt bootstrap` or equivalent shortcut that creates a common starter project with one approval step, one typed tool, JSONL logs, optional SQLite mirroring, and a known-good `replayt ci` example so a single engineer can get to a credible local demo quickly.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 9. Enterprise integrator - Policy-backed approval broker
- **Request:** Add first-class resume-time policy hooks for SSO identity claims, ticket references, resolver allowlists, and attestation payloads so approvals can be mediated by existing enterprise controls.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This edges into a hosted approval or RBAC layer, which conflicts with **Local-first by default**, **Tiny mental model**, and the **Hosted approval UI, multi-user queues, team RBAC** row in [`docs/SCOPE.md`](./SCOPE.md).
- **Suggested overcome:** Keep replayt as the local engine and put identity plus policy in your wrapper or broker. The existing subsection [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks** plus **Pattern: approval bridge (local UI)** and **Pattern: webhook / lifecycle callbacks** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md) already shows the supported approach.

### 10. Framework enthusiast - Built-in agent runtime
- **Request:** Embed LangGraph-style planners, token streaming, tool loops, and dynamic sub-agents directly in `Runner` so replayt becomes the framework runtime instead of a narrow replayable FSM.
- **Aligns with principles:** no
- **Scope:** compose outside core
- **Principle / scope tension:** This conflicts with **Determinism over autonomy**, **Explicit states over hidden loops**, and the **LangChain / LangGraph / "agent framework" integration** row in [`docs/SCOPE.md`](./SCOPE.md); planner-internal events and dynamic states would bury the replay log.
- **Suggested overcome:** Keep the framework inside one replayt step, validate one exit shape, and return an explicit next state. The existing subsections [`README.md`](../README.md) under **Streaming, planner loops, and "agents" (composition, not core)** and [`src/replayt_examples/README.md`](../src/replayt_examples/README.md) under **LangGraph (and similar frameworks) - composition, not core**, plus **Pattern: framework in a sandbox step** and **Pattern: stream inside step, log structured summary** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md), already cover the recommended composition pattern.

## Summary table

| # | Archetype | Feature | Aligns | Scope |
|---|-----------|---------|--------|-------|
| 1 | Staff engineer / platform | Workflow compatibility profile | yes | in-core candidate |
| 2 | Junior dev onboarding | First-run scaffold with replay path | yes | in-core candidate |
| 3 | Security / compliance | Auditable log-policy manifest | yes | in-core candidate |
| 4 | ML / LLM engineer | Eval matrix runner | partial | compose outside core |
| 5 | DevOps / SRE | Container readiness doctor | yes | in-core candidate |
| 6 | Product engineer | Local approval inbox snapshot | yes | in-core candidate |
| 7 | Open-source maintainer | Workflow package manifest | yes | in-core candidate |
| 8 | "Just ship it" startup IC | Bootstrap happy path | yes | in-core candidate |
| 9 | Enterprise integrator | Policy-backed approval broker | partial | compose outside core |
| 10 | Framework enthusiast | Built-in agent runtime | no | compose outside core |
