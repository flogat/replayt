## Archetype feature brainstorm (10)

### 1. Staff engineer / platform - Strict workflow contract profile
- **Request:** Add a stricter `replayt validate --profile contract` mode that enforces declared transitions, workflow metadata version fields, retry-policy coverage for selected states, and stable deprecation warnings for renamed workflow entrypoints.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 2. Junior dev onboarding - Copy-paste starter workflows
- **Request:** Extend `replayt init` with a few tiny starter templates such as `hello`, `approval`, and `review`, each wired to `replayt_examples`-style comments, `.env` hints, `replayt doctor`, and a known-good `replayt run ...` or `--dry-check` command.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 3. Security / compliance - Event-level redaction policy labels
- **Request:** Let operators tag runs with a named redaction policy and record which fields were masked, skipped, exported, or sealed so audit reviewers can tell whether a run used `LogMode.redacted`, `structured_only`, a stricter PII profile, or a `replayt seal` / `bundle-export` handoff.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 4. ML / LLM engineer - Logged provider preset diffs
- **Request:** Add reusable provider presets on `LLMBridge` that still stay explicit by logging the full `effective` settings delta per step, including provider slug, response format mode, timeout, schema fingerprint, and `ctx.llm.with_settings(experiment=...)` tags.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 5. DevOps / SRE - CI readiness doctor
- **Request:** Add a `replayt doctor --ci` mode that checks writable log paths, expected env vars, SQLite mirror availability, configured `resume_hook` commands, and safe `--format json` failure messages for containerized or queue-worker deployments.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 6. Product engineer - Stakeholder handoff report bundle
- **Request:** Expand `replayt report --style stakeholder` / `bundle-export` output with a compact handoff packet that highlights approvals, final decision, structured outputs, replay timeline links, and failure points without exposing raw prompt text by default.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 7. Open-source maintainer - Public workflow package contract
- **Request:** Add a small manifest convention for reusable workflow packages so maintainers can publish stable import targets, declared examples, minimum replayt version, and deprecation notes without introducing runtime plugin loading.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 8. "Just ship it" startup IC - Batteries-included local stack
- **Request:** Ship a one-command local happy path for the common case: JSONL logs, optional SQLite mirror, one approval checkpoint, one HTML replay/report export, and a `replayt ci` example that fails clearly instead of requiring a long setup pass.
- **Aligns with principles:** yes
- **Scope:** in-core candidate

### 9. Enterprise integrator - Policy-gated resume broker
- **Request:** Add first-class pre-`resume` policy hooks for SSO-backed approval forms, resolver allowlists, change-ticket checks, and audit attestations so enterprise teams can gate human approvals through existing controls.
- **Aligns with principles:** partial
- **Scope:** compose outside core
- **Principle / scope tension:** This pushes replayt toward a hosted approval or RBAC surface, which conflicts with **Local-first by default**, **Tiny mental model**, and the **Hosted approval UI, multi-user queues, team RBAC** row in [`docs/SCOPE.md`](./SCOPE.md).
- **Suggested overcome:** Keep replayt as the local `Runner` and put identity, policy, and ticket checks in your wrapper: use [`README.md`](../README.md) under **Policy hooks, eval-style harnesses, and agent frameworks** plus **Pattern: approval bridge (local UI)** and **Pattern: webhook / lifecycle callbacks** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md).

### 10. Framework enthusiast - Built-in LangGraph-style agent runtime
- **Request:** Embed planner graphs, token streaming, multi-agent loops, and framework-native checkpoints directly into `Runner` so replayt becomes the main orchestration surface for agent frameworks.
- **Aligns with principles:** no
- **Scope:** compose outside core
- **Principle / scope tension:** This conflicts with **Explicit states over hidden loops**, **Replay is part of the product**, and the **LangChain / LangGraph / "agent framework" integration** row in [`docs/SCOPE.md`](./SCOPE.md); per-token and planner-internal events would bury the explicit replay log.
- **Suggested overcome:** Keep external frameworks inside one replayt step and emit one validated exit shape. The existing tutorial subsection [`src/replayt_examples/README.md`](../src/replayt_examples/README.md) under **LangGraph (and similar frameworks) - composition, not core** and **Pattern: framework in a sandbox step** plus **Pattern: stream inside step, log structured summary** in [`docs/EXAMPLES_PATTERNS.md`](./EXAMPLES_PATTERNS.md) already document the supported shape.

## Summary table

| # | Archetype | Feature | Aligns | Scope |
|---|-----------|---------|--------|-------|
| 1 | Staff engineer / platform | Strict workflow contract profile | yes | in-core candidate |
| 2 | Junior dev onboarding | Copy-paste starter workflows | yes | in-core candidate |
| 3 | Security / compliance | Event-level redaction policy labels | yes | in-core candidate |
| 4 | ML / LLM engineer | Logged provider preset diffs | yes | in-core candidate |
| 5 | DevOps / SRE | CI readiness doctor | yes | in-core candidate |
| 6 | Product engineer | Stakeholder handoff report bundle | yes | in-core candidate |
| 7 | Open-source maintainer | Public workflow package contract | yes | in-core candidate |
| 8 | "Just ship it" startup IC | Batteries-included local stack | yes | in-core candidate |
| 9 | Enterprise integrator | Policy-gated resume broker | partial | compose outside core |
| 10 | Framework enthusiast | Built-in LangGraph-style agent runtime | no | compose outside core |
