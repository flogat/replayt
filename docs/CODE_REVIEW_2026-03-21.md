# Deep Code Review - 2026-03-21

## Overall assessment

The repository is in better shape than it was in the earlier review pass. The core runtime, export sanitization, and CLI correctness issues called out previously are fixed, and `python -m pytest -q` is currently green in this workspace (`198 passed, 3 skipped`). The remaining risks are concentrated in operator-facing reporting and release automation rather than the run engine itself, so deeper remediation is still warranted before treating every generated report or CI gate as a reliable audit control.

## Critical

None.

## High

None.

## Medium

### `report-diff` still collapses repeated structured outputs by schema name

**Why it matters**  
The HTML diff is supposed to explain how two runs diverged. Today it still reduces structured outputs to one entry per `schema_name`, so earlier outputs are overwritten by later ones. A workflow that emits the same schema twice can therefore produce a diff that says the runs match even when the first decision differed materially.

**Evidence from the code**  
`_outputs_signature()` reduces the entire output list to a dict keyed only by schema name in [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L317). `build_report_diff_html()` then compares only those collapsed dicts in [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L376). In a local reproduction with two `Decision` outputs per run, where only the first payload differed, `build_report_diff_html()` still rendered `<p class="rp-diff-row"><span class="rp-label">Decision:</span> match</p>`.

**Concrete recommendation**  
Preserve multiplicity in the diff input. Compare ordered `structured_output` occurrences by `(schema_name, seq)` or by stable occurrence index, then render per-occurrence differences instead of a last-write-wins summary.

### Approval reporting loses audit fidelity, and `report-diff` misses outcome changes

**Why it matters**  
Approval events are an audit surface. The current report aggregation keeps only one request, one resolution flag, and one resolution timestamp per `approval_id`, so repeated uses of the same ID overwrite earlier occurrences. On top of that, the HTML diff ignores approval outcomes entirely, so an approved run and a rejected run can look identical in the comparison output.

**Evidence from the code**  
`aggregate_run_report_data()` stores approvals in dicts keyed only by `approval_id` in [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L205), overwriting request metadata at [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L258) and keeping only the last resolution boolean/timestamp at [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L264). `build_report_diff_html()` then compares only `approval_requests` counts and IDs, not `approval_last` or timestamps, in [`src/replayt/cli/report_template.py`](../src/replayt/cli/report_template.py#L406). In a local reproduction, one run resolved `approval_id="ship"` with `approved=True` and another with `approved=False`; the diff still reported only `A approvals: 1 - B approvals: 1`.

**Concrete recommendation**  
Represent approvals as ordered occurrences rather than per-ID maps. Pair each `approval_requested` with its corresponding `approval_resolved` event, preserve every occurrence, and diff both the request metadata and the resolved outcome.

### The PR changelog gate fails open when `git diff` fails

**Why it matters**  
This script is the repository's enforcement point for "protected paths require a changelog update." If the underlying git query fails in CI, the script currently prints an error and exits successfully, which silently disables the policy for that run.

**Evidence from the code**  
`main()` catches `subprocess.CalledProcessError` around `changed_files_vs_base()`, prints a diagnostic, and returns `0` in [`scripts/check_changelog_if_needed.py`](../scripts/check_changelog_if_needed.py#L40). The current tests cover the path-matching policy in [`tests/test_changelog_gate.py`](../tests/test_changelog_gate.py), but there is no test for the failure path.

**Concrete recommendation**  
Fail closed here: return a non-zero exit code when the diff step cannot determine the changed files. If there is a legitimate reason to soft-skip in some environments, gate that behavior behind an explicit opt-out or a more specific exception path than "any git diff failure."

## Low

### Skill-release default order contradicts the repo documentation

**Why it matters**  
The release loop is meant to be a repeatable automation path. Right now the repository documents one default skill order, while the script and its default task execute another. That mismatch makes the workflow harder to reason about and can invalidate operator expectations about when code-fixing versus doc-toning runs happen.

**Evidence from the code**  
`CONTRIBUTING.md` documents the default order as `createfeatures`, `improvedoc`, `deslopdoc`, `reviewcodebase` in [`CONTRIBUTING.md`](../CONTRIBUTING.md#L49). The script hard-codes `("createfeatures", "improvedoc", "reviewcodebase", "deslopdoc")` and repeats that order in `DEFAULT_TASK` in [`scripts/skill_release_loop.py`](../scripts/skill_release_loop.py#L17). The current release-loop test also locks in the script order in [`tests/test_skill_release_loop.py`](../tests/test_skill_release_loop.py#L264).

**Concrete recommendation**  
Choose one canonical order and centralize it in one place that both the script and documentation derive from. Then update the test to assert that single source of truth rather than a duplicated literal.

## Potential concerns / assumptions

- Assumption: the `anthropic` provider preset is intended only for OpenAI-compatible Anthropic gateways, not the native Anthropic API. The inline comment says the native API is not OpenAI-compatible, but the preset still points at `https://api.anthropic.com/v1` while the client appends `/chat/completions`; see [`src/replayt/llm.py`](../src/replayt/llm.py#L102). I am treating this as a concern rather than a confirmed defect because I did not execute a live request in this review pass.
- Assumption: stakeholder users rely on `report-diff` as an audit artifact, not just a convenience summary. The reporting defects above are still worth fixing either way, but the severity is highest if those HTML diffs are used in approval or incident workflows.

## What is good

- The previously documented runtime bugs around hook failures, export redaction, doctor JSON health, dry-run parsing, and recent-run ordering are fixed in code and covered by tests.
- The runtime failure path is now much more coherent: unexpected exceptions still emit `run_failed` plus terminal `run_completed`, which makes downstream consumers easier to write and trust.
- The persistence layer remains one of the strongest parts of the codebase. The JSONL and SQLite stores are explicit about sequencing, locking, and corruption handling instead of hiding those edges behind broad retries.
- The CLI is decomposed into focused modules, which keeps command behavior readable and makes targeted testing practical.

## Missing tests

- A `report-diff` regression test where two runs emit the same schema twice and only the first occurrence differs.
- A report/diff test where the same `approval_id` appears multiple times in one run, proving that every occurrence is preserved and paired correctly.
- A `report-diff` test where the approval request metadata is identical but the resolution outcome differs (`approved` vs `rejected`).
- A changelog-gate test that forces `changed_files_vs_base()` to fail and asserts that the script exits non-zero.
- A release-loop consistency test that fails if the documented skill order and the scripted default order drift apart again.

## Refactoring opportunities

- Introduce a small event-normalization layer for reports that produces ordered approval and structured-output occurrence objects once, then reuse that representation in single-run reports, HTML diffs, and any future machine-readable exports.
- Replace the duplicated skill-order literals in docs, script constants, and tests with one canonical definition that can be rendered into help text and documentation.
- Give `check_changelog_if_needed.py` a narrower "environment could not determine changed files" branch instead of collapsing every git failure into a silent pass.

## Summary verdict

The repository is production-ready for core workflow execution, but it still needs improvement in its reporting and release-governance surfaces. I would trust the run engine far more than I would trust the current HTML diff output or the changelog CI gate. The next pass should focus on preserving event multiplicity in reports, diffing approval outcomes correctly, and making the changelog check fail closed.
