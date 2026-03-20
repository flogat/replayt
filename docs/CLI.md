# CLI reference

All commands support Typer’s `--help`. Most read/write commands accept `--log-dir` and optional `--sqlite` unless noted; defaults match [`CONFIG.md`](CONFIG.md) when you use project config.

## `replayt init [--path DIR] [--force]`

Write `workflow.py` and `.env.example`. Refuses to overwrite unless `--force`.

## `replayt run TARGET`

Run a workflow from a module reference, Python file, or YAML file. Common flags: `--output text|json`, `--log-mode …`, `--resume`, `--tag key=value` (repeatable), `--timeout SECONDS`, `--inputs-json …`.

**Exit codes:** `0` completed, `1` failed, `2` paused (approval required).

`TARGET` can be:

- `module:variable` (e.g. `examples.e01_hello_world:wf`)
- `workflow.py` (must export `wf` or `workflow`)
- `workflow.yaml` / `workflow.yml` (requires `pip install replayt[yaml]`)

## `replayt inspect RUN_ID`

Summary and event list for a run. `--output json` (or legacy `--json`) prints `{"summary": …, "events": …}`.

## `replayt replay RUN_ID`

Recorded execution timeline **without** calling model APIs. `--format html` emits a self-contained page (Tailwind CDN); `--out PATH` writes a file.

## `replayt report RUN_ID`

Self-contained HTML report (summary, states, structured outputs, tool calls). `--out PATH` writes a file; omit `--out` for stdout.

## `replayt resume TARGET RUN_ID --approval ID`

Resolve an approval gate and continue a paused run. Same exit codes as `run`. Use `--reject` to reject the approval.

## `replayt graph TARGET`

Print a Mermaid graph of the workflow to stdout.

## `replayt validate TARGET`

Validate workflow graph without calling an LLM: initial state set, transition targets exist, no orphan states, handlers present. Exit `0` if valid, `1` if not. CI-friendly.

## `replayt diff RUN_A RUN_B`

Compare two runs: states visited, structured outputs, tool calls, status, latency. `--output json` for machine-readable output.

## `replayt gc --older-than DURATION`

Delete JSONL run logs older than a duration (`90d`, `24h`, …). `--dry-run` to preview.

## `replayt runs`

List recent local runs. `--tag key=value` (repeatable) to filter.

## `replayt stats [--days N] [--tag key=value] [--output text|json]`

Aggregate counts, average `llm_response` latency, token usage, top failure states, event time range.

## `replayt doctor`

Check install, env vars, optional YAML extra, and default provider connectivity.
