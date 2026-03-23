# Examples

Work through these examples in order.

Each section covers four things:

- **Why this example exists**
- **What the workflow code does**
- **What command to run**
- **What you should see**

New to replayt? Start with [`docs/QUICKSTART.md`](../../docs/QUICKSTART.md), then read the sections below **in order**. There are **14** runnable workflows here (sections 1-12, plus OpenAI and Anthropic SDK examples). They move from a two-step deterministic run to LLM-backed classification, typed tools, retries, and approval gates. After a few runs, you should be able to open each source file, read the state handlers, and match them to what you see in `inspect` and `replay`.

**Patterns and recipes** (approval bridge, batch driver, async apps, dashboards, encryption sketches, and more) are in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)** so this page can stay a straight-line tutorial.

<p align="center">
  <img src="../../docs/demo-why.svg" alt="typical agent framework vs replayt" width="820"/>
</p>

## How to use this tutorial README

1. Read one section in this file.
2. Open the corresponding source file in `src/replayt_examples/`.
3. Run the example exactly as shown.
4. Inspect the run and compare the resulting context and events with the explanation here.
5. Change the sample input and run again to see different behavior.

### Optional: interactive onboarding TUIs and terminal recordings

Built-in onboarding wizards and record/play helpers stay out of core so install stays small and shell history stays explicit. Use **`docs/QUICKSTART.md`**, **`replayt try --list`**, **`replayt doctor`**, and the numbered sections below as your checklist. For a shareable terminal demo, record with **asciinema** (or any screen recorder) in your own repo, or start from **`docs/DEMO.md`** and the checked-in cast **`docs/replayt-demo.cast`**.

### Install (PyPI, no clone required)

```bash
pip install replayt
# pip install replayt[yaml]  # if you run .yaml / .yml workflow targets
replayt doctor
export OPENAI_API_KEY=...   # only for sections that call a live model
```

### Doctor stays offline-friendly; upgrade replayt yourself

`replayt doctor` does not run `pip install --upgrade` for you or require a successful live LLM call before the command is considered done. Pin **replayt** in your environment the same way you pin other dependencies, then upgrade with your usual toolchain when you need a newer release, for example `pip install -U replayt` or `uv pip install -U replayt`. When you only want import and graph checks, use `replayt doctor --skip-connectivity --target YOUR_MODULE:wf`. Compare the running build with `replayt version` (and the tag you deploy from) when triaging behavior differences.

Runnable tutorials ship in the **`replayt_examples`** package on PyPI (namespaced so it does not collide with a generic `examples` module in your own code).

### Install path and docs without extra `replayt` commands

Core stays free of **`replayt which`**-style helpers and browser launchers so shells and air-gapped machines stay predictable. To see where the wheel landed, use **`pip show replayt`** or **`python -c "import replayt; print(replayt.__file__)"`**. For prose docs, open **`README.md`** and **`docs/QUICKSTART.md`** in your checkout, or browse the same paths on GitHub for the tag that matches the version you pinned. There is no bundled **`replayt env`** command: compare raw shell exports with merged project settings via **`env | grep REPLAYT`** (PowerShell: **`Get-ChildItem Env:REPLAYT_*`**) and **`replayt config --format json`** in the same working directory.

To skip reading this file front to back, run `replayt try --list` (each entry ends with a copy-paste `replayt try --example KEY` line), then run that command or pick another key. Use `replayt try --list --output json` when you want **`replayt.try_examples.v1`**: every example includes a **`cli`** object (`try_offline`, `try_live`, `try_dry_check`, `copy_to_dot`) for scripts and internal docs. Add `--inputs-file my-inputs.json` when you want the same example shape with your own payload. To edit the tutorial code in your repo, run `replayt try --example KEY --copy-to ./my-flow` (writes `workflow.py`, `inputs.example.json`, and `.replaytrc.toml`; use `--force` to replace). The text output prints `doctor --skip-connectivity --target workflow.py`, then bare `replayt run --dry-check` / `replayt run`, with `--dry-run` first when the copied example uses an LLM. When you already have **`workflow.py`** (copy-to, hand-written, or vendored) but **`.gitignore`** never picked up **`.replayt/`** or local env files, run **`replayt init-gitignore`** in that directory. That adds the same lines **`replayt init`** would append, without touching scaffold files.

When you are greenfielding your own repo instead of copying a tutorial, run **`replayt init --list`** to see scaffold keys (each entry prints **`replayt init --template KEY`** plus a portable **`replayt run <file> --inputs-file …`** line for that template). **`replayt init --list --output json`** emits **`replayt.init_templates.v1`** with copy-paste strings under **`cli`**: **`init_here`**, **`init_with_ci_github`**, **`doctor_target`**, explicit **`validate_explicit`** / **`dry_check_explicit`** / **`run_explicit`** / **`ci_dry_check_explicit`**, bare **`dry_check`** / **`run`** (after **`.replaytrc.toml`** is in place), and LLM-backed templates include **`dry_run`**. Core does not auto-open an editor or browser after init; open the new `workflow.py` or `workflow.yaml` from the tool you already use. Core does not ship a one-shot **`replayt bootstrap`** that chains init, doctor, and the first run; keep those as separate commands or an **`&&`** line in **your** script so shell history stays explicit.

### Fast input overrides without a JSON blob

For quick local runs, repeat **`--input key=value`** instead of writing a whole **`--inputs-json`** object. Dotted keys build nested objects, and replayt parses JSON-style scalars when it can, so **`--input priority=2 --input needs_review=false`** becomes structured input instead of raw strings. This also layers on top of packaged example defaults when you change just one field in a tutorial payload.

```bash
replayt try --example issue-triage \
  --input issue.title="Crash on save" \
  --input issue.body="Open app, click save, white screen."
```

### Default target for `replayt run` / `replayt ci`

When you are iterating on one workflow, avoid repeating the module path on every command. Set **`REPLAYT_TARGET=my_pkg.workflow:wf`** in your environment, or add **`target = "my_pkg.workflow:wf"`** under **`[tool.replayt]`** (or in **`.replaytrc.toml`**). `replayt init` and `replayt try --copy-to` already do this for the scaffolded local `workflow.py`. Then you can run:

```bash
replayt run --dry-run --inputs-file inputs.example.json
```

An explicit **`TARGET` positional argument always overrides** the default. Check what applies in your shell with **`replayt config --format json`** (`run.default_target`, `run.default_target_source`). **`replayt resume`**, **`replayt validate`**, **`replayt graph`**, and **`replayt contract`** still require a target on the command line (or **`doctor --target`** for preflight only).

### Common `TARGET` mistakes (first hour)

`replayt run` accepts **`module:variable`**, a trusted **`.py` / `.yaml`** path, or a default from **`REPLAYT_TARGET`** / project config. A dotted import path without a colon is not a valid target: use **`replayt_examples.e01_hello_world:wf`**, not the module alone. If you meant a local file, include the extension when **`workflow.py`** exists beside you. **JSON inputs are not a `TARGET`:** if you pass a path to an existing **`.json`** file in the first slot, replayt errors with a copy-paste pattern such as **`replayt run workflow.py --inputs-file inputs.example.json`** (or set **`inputs_file`** under **`[tool.replayt]`** / **`.replaytrc.toml`**). On Windows, absolute paths like **`C:\path\to\workflow.py`** stay filesystem paths (the drive-letter colon is not read as **`MODULE:VAR`**). replayt does not download workflow code from arbitrary URLs or fuzzy-guess misspelled module names; vendor or pin workflows as normal Python packages or checked-in files, use shell or IDE completion, and discover packaged keys with **`replayt try --list`**. Core also does not add magic shortcuts (for example **`replayt hello`**) that run a packaged workflow without an explicit target string you can grep in shell history.

```bash
replayt doctor --skip-connectivity --target replayt_examples.e01_hello_world:wf
```

### Default inputs file for `replayt run` / `replayt ci` / `validate`

When you always pass the same **`inputs.example.json`**, set **`REPLAYT_INPUTS_FILE=inputs.example.json`** (or an absolute path) in your environment, or add **`inputs_file = "inputs.example.json"`** under **`[tool.replayt]`**. `replayt init` and `replayt try --copy-to` already wire this into the generated `.replaytrc.toml`. Then you can shorten:

```bash
replayt run --dry-run
replayt validate my_pkg.workflow:wf
```

CLI **`--inputs-json`** / **`--inputs-file`** still override. Inspect effective paths with **`replayt config --format json`** (`run.default_inputs_file`, `run.default_inputs_file_source`). **`replayt try`** ignores this default so packaged samples keep their built-in payloads unless you pass **`--inputs-json`** or **`--inputs-file`** explicitly.

### Reuse inputs from a finished run

When you want the same **`run_started.inputs`** payload again (debugging, A/B on prompts, or a teammate’s run id), dump the logged object and pass it explicitly. **`TARGET`** still comes from **`MODULE:VAR`**, project config, or **`REPLAYT_TARGET`**, not from the JSONL file.

```bash
RUN_ID=...   # from replayt run output or replayt runs
replayt inspect "$RUN_ID" --print-inputs
replayt run "$TARGET" --inputs-json "$(replayt inspect "$RUN_ID" --print-inputs)"
```

On bash you can also write the blob once: **`replayt inspect "$RUN_ID" --print-inputs > last-inputs.json`** then **`replayt run "$TARGET" --inputs-json @last-inputs.json`**. Redacted keys replay as **`{"_redacted": true}`** when the original run used **`--redact-key`**; fix those fields before a live rerun if the workflow requires real values.

### Install (from this repository)

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=...
# Optional: load from .env in your shell (replayt does not read .env by itself)
# set -a && source .env && set +a   # bash, if .env is export-safe
# direnv allow                        # if you use direnv + .envrc
```

See [`README.md`](../../README.md) for Windows activation lines, `replayt doctor`, optional extras (`[yaml]`), and LLM env vars (`OPENAI_BASE_URL`, `REPLAYT_MODEL`).

## Tests without a live LLM (CI and pytest)

Sections **1-5** of this tutorial need **no API key**. For LLM-backed workflows in **automated tests**, use **`MockLLMClient`** with **`run_with_mock`** (or mock `httpx`) and assert on context or JSONL events. See **Pattern: golden path test (pytest)** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md). For **`replayt validate`** and CI exit codes, see [`docs/RECIPES.md`](../../docs/RECIPES.md).

### CI images and explicit flags

replayt does not ship a blessed container image: your registry, Python minor, and whether you need **`replayt[yaml]`** belong in **your** Dockerfile or CI job. A typical pattern is a slim Python base, install the package, then call **`replayt ci`** with the same flags you want everywhere (**`--strict-graph`**, **`--summary-json`**, **`--junit-xml`**) instead of relying on implicit environment detection.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"
ENV REPLAYT_GITHUB_SUMMARY=1
ENV REPLAYT_STEP_SUMMARY=/tmp/replayt-step-summary.md
CMD ["replayt", "ci", "your_pkg.workflow:wf", "--strict-graph", "--summary-json", ".replayt/ci-summary.json"]
```

GitHub Actions sets **`GITHUB_STEP_SUMMARY`** for you; in other runners set **`REPLAYT_STEP_SUMMARY`** to a path under your artifacts directory so the same markdown block is not a silent no-op. When both **`GITHUB_STEP_SUMMARY`** and **`REPLAYT_STEP_SUMMARY`** exist, replayt appends to the GitHub file only.

For GitHub Actions, keep **`--github-summary`** or **`REPLAYT_GITHUB_SUMMARY=1`** explicit in the workflow file so local shells do not pick up surprising markdown behavior.

### Beyond core: explicit CI artifact paths and log forwarding

Some templates want one **`--artifacts-dir`** with fixed filenames for JUnit, **`replayt.ci_run_summary.v1`**, and markdown. replayt keeps those paths **explicit** so upload globs and retention policies stay obvious in job YAML. Point **`REPLAYT_STEP_SUMMARY`** at a file beside the other outputs:

```bash
ART="$GITHUB_WORKSPACE/replayt-ci"
mkdir -p "$ART"
export REPLAYT_STEP_SUMMARY="$ART/step-summary.md"
replayt ci "$TARGET" --strict-graph \
  --junit-xml "$ART/junit.xml" \
  --summary-json "$ART/summary.json" \
  --github-summary
```

For pipeline branching on **`replayt run` / `ci` / `resume` / `try`** without rereading prose docs, consume **`cli_exit_codes`** from **`replayt version --format json`** (stable alongside **`cli_machine_readable_schemas`**).

**`replayt.ci_run_summary.v1`** carries **`cwd`**, **`replayt_version`**, **`python_version`**, **`python_executable`**, and **`platform`** next to **`run_id`** and **`exit_code`**, so an uploaded **`summary.json`** stays self-describing when you compare flaky jobs across image, venv, or working-directory mistakes:

```bash
jq '.cwd, .python_executable, .replayt_version, .python_version, .platform, .exit_code' "$ART/summary.json"
```

### Beyond core: richer JUnit matrices and shell transcripts

Some dashboards want **one JUnit testcase per workflow state**, or a **full tty transcript** with ANSI color like a **`script(1)`** session. replayt keeps **one testcase** in the bundled JUnit file so pass/fail semantics stay obvious; derive finer-grained rows from **`state_entered`** lines in JSONL or rewrite JUnit in your CI step. For transcripts, wrap **`replayt ci`** with **`script`** (or your platform's log capture) so pseudo-tty policy stays in the container image:

```bash
script -qec 'replayt ci "$TARGET" --strict-graph --summary-json summary.json' /tmp/ci-transcript.txt
```

To print the **effective** JSONL log directory and env-resolved CI paths for the **current working directory** (same **`log_dir`** rules as **`replayt run`** / **`replayt doctor`**), read **`operational_paths`** on **`replayt version --format json`**:

```bash
replayt version --format json | python -c "import json,sys; p=json.load(sys.stdin)['operational_paths']; print(p['effective_log_dir'], p['ci_artifact_paths'])"
```

To fail a setup job before **`replayt ci`** when **`REPLAYT_JUNIT_XML`** or **`REPLAYT_SUMMARY_JSON`** points at a bad path (or when **`REPLAYT_GITHUB_SUMMARY=1`** without a step-summary file), assert **`ci_artifact_readiness_ok`** or inspect **`ci_artifact_readiness`** on the same object:

```bash
replayt version --format json | jq -e '.operational_paths.ci_artifact_readiness_ok' >/dev/null
```

### Beyond core: disk quotas and Prometheus-style metrics in CI

replayt does **not** hard-fail **`replayt doctor`** when a builder is low on disk, and **`replayt ci`** does **not** emit OpenMetrics or Prometheus text on stdout. Free-space floors and scrape formats vary by runner image and monitoring stack. Probe the workspace volume with **`df`**, **`wmic`**, or your cloud agent before **`replayt ci`**, and turn **`replayt.ci_run_summary.v1`** or JSONL events into gauges in **your** metrics pipeline.

replayt does **not** tee JSONL to **stdout**: treat **`.replayt/runs/*.jsonl`** as the audit source and tail or ship them with your log agent instead of turning the workflow process into a log forwarder.

### Beyond core: supervisor readiness hooks (systemd notify)

Some teams want **`replayt ci`** integrated with **systemd** **`Type=notify`** units, **`sd_notify`**, or watchdog pings on a notify socket. Socket paths, cgroup visibility, and whether the **Python** process or a parent wrapper must send **`READY=1`** vary by unit layout and container images. replayt does **not** embed systemd notify calls: use **`Type=simple`** for straight **`ExecStart=replayt ci …`**, or wrap **`replayt ci`** in a shell script that runs **`systemd-notify`** (or your platform's equivalent) with argv your SRE team owns.

```ini
[Service]
Type=simple
ExecStart=/usr/bin/replayt ci mypkg.workflow:wf --strict-graph --summary-json /var/lib/ci/summary.json
```

### Beyond core: streaming stderr progress lines for log aggregators

Some aggregators want **NDJSON** or **structured stderr** lines while **`replayt ci`** runs so dashboards update before the workflow finishes. Framing, sampling, and secret redaction rules differ by vendor; replayt stays off stderr except human text and Typer errors. Tail **`.replayt/runs/*.jsonl`**, poll **`replayt inspect`**, or scrape **`--summary-json`** after the process exits instead of adding a second streaming protocol in core.

### Beyond core: auto-filled `ci_metadata` from vendor env vars

Some pipelines want **`replayt.ci_run_summary.v1`** enriched with **`GITHUB_SHA`**, **`CI_COMMIT_SHA`**, or similar **without** a shell mapping step. replayt does **not** read those variables implicitly: which names matter and how they are normalized varies by vendor, and silent coupling would surprise self-hosted or air-gapped jobs. Export **`REPLAYT_CI_METADATA_JSON`** yourself (for example `jq -n --arg sha "$CI_COMMIT_SHA" '{commit_sha:$sha}'`) so correlation fields stay explicit. See [`docs/CONFIG.md`](../../docs/CONFIG.md).

### Beyond core: strict project-config checks in CI (unknown keys, shadowed pyproject, min version)

Some teams ask for **`replayt config --strict`** that exits non-zero when **`[tool.replayt]`** contains unsupported keys. replayt treats unknown keys as **ignored** at runtime so a hyphen typo does not brick every local shell, and there is no bundled strict subcommand. Use the **CI: fail on unknown keys** snippet in [`docs/CONFIG.md`](../../docs/CONFIG.md). The same pattern covers **`project_config.shadowed_sources`**: when **`.replaytrc.toml`** and **`pyproject.toml`** **`[tool.replayt]`** both exist in one directory, only the rc file loads; CI can fail if that list is non-empty so edits land in the file replayt actually reads. When you pin **`min_replayt_version`**, also assert **`project_config.min_replayt_version_satisfied`** from **`replayt config --format json`** so upgrade drift fails in CI before **`replayt run`**:

```bash
replayt config --format json | python -c "import json,sys; d=json.load(sys.stdin)['project_config']; u=d.get('unknown_keys') or []; s=d.get('shadowed_sources') or []; m=d.get('min_replayt_version'); sat=d.get('min_replayt_version_satisfied', True); bad=bool(u) or bool(s) or (m is not None and not sat); sys.exit(1 if bad else 0)"
```

### Beyond core: org-wide defaults and stable CLI entrypoints

Some platform teams want **one HTTP-served `[tool.replayt]` blob** merged into every checkout, or **built-in long-lived Typer aliases** so old flags keep working across many releases. replayt keeps config **local-first** (nearest **`.replaytrc.toml`** / **`pyproject.toml`** wins) and argv **explicit**; fetching remote TOML would hide provenance and merge rules, and bundled deprecation shims would duplicate Click/Typer introspection and drift from docs. Distribute defaults with **template repositories**, **`REPLAYT_*`** exports in CI matrix rows, or a checked-in **`.replaytrc.toml`** you copy from an internal cookiecutter. When engineers need a shorter command, add a **Makefile** target, **`just`** recipe, or shell function that forwards argv to **`replayt`**. Gate interpreters the same way you gate package versions:

```bash
replayt version --format json | python -c "import json,sys; d=json.load(sys.stdin); assert d['python']['implementation']['name']=='cpython', d['python']['implementation']"
```

### Beyond core: immutable log volumes (WORM-style retention)

Some compliance programs want **write-once** run logs: OS immutable bits, S3 Object Lock, GCS retention policies, or air-gapped tape. replayt does **not** toggle **`chattr`**, object-lock legal holds, or cloud retention APIs from **`Runner.run`**: the right enforcement depends on your filesystem, cloud account, and records program. Treat JSONL as normal files under **`.replayt/runs`**, then **seal** and **ship** to storage your legal team blesses. Use **`forbid_log_mode_full = true`** or **`REPLAYT_FORBID_LOG_MODE_FULL=1`** when archives must not contain raw LLM bodies (see [`docs/CONFIG.md`](../../docs/CONFIG.md)).

```bash
replayt seal "$RUN_ID" --log-dir .replayt/runs --out "runs/${RUN_ID}.seal.json"
replayt verify-seal "$RUN_ID" --log-dir .replayt/runs
# Then upload runs/ to your WORM bucket or vault with your org's tooling.
```

### Beyond core: enforce `.env` permissions in CI

replayt inspects **`.env`** mode bits (never file contents) for **`trust_dotenv_other_readable`** / **`trust_dotenv_other_writable`** in **`replayt doctor`** and **`replayt config --format json`** on POSIX. Core does **not** refuse to run when a file is too permissive; teams with shared checkouts or loose umask values would churn. Treat weak modes as a **release gate** instead: fail CI when those doctor checks are not ok, or assert mode bits with `stat` / `ls -l` in your pipeline. Loading **`.env`** stays **your** responsibility. Do not expect **`Runner.run`** to call **python-dotenv** implicitly.

```bash
replayt doctor --skip-connectivity --format json | python -c "import json,sys; d=json.load(sys.stdin); bad=[c for c in d['checks'] if c['name'].startswith('trust_dotenv_') and not c['ok']]; sys.exit(1 if bad else 0)"
```

### Beyond core: SARIF, vendor CI YAML, and Kubernetes Job specs

Some teams want **SARIF** uploads, checked-in **GitLab**/**Circle** job definitions, or **Kubernetes Job** manifests co-located with replayt. Those formats are policy- and cluster-specific; replayt stays a workflow runner and emits **JUnit**, **GitHub step summaries** (when asked), and **`replayt.ci_run_summary.v1`** JSON instead of owning a security-scanner interchange or a blessed platform template repo. Generate SARIF or wrap Job YAML in **your** infra repository: drive **`replayt ci`** the same way as in any container, then post-process **`--summary-json`** with **`jq`** or a small script. For Kubernetes, mount your code image and run the same argv you use in GitHub Actions. No replayt-side operator is required.

### Beyond core: dependency scanners and Dependabot

Some maintainers want **`replayt doctor`** to run **`pip-audit`**, **`safety`**, or similar dependency scanners, or want replayt to ship a **Dependabot** configuration. Tooling choice, lockfiles, and registry mirrors differ by team; bundling scanners would pin databases and slow every doctor run. Add **Dependabot** or **Renovate** YAML under **`.github/`** in **your** repository, and run **`pip-audit -r requirements.txt`** (or your lockfile workflow) as its own CI job beside **`python scripts/maintainer_checks.py`**. For release-note text without an interactive wizard, extract **`## Unreleased`** with **`python scripts/changelog_unreleased.py --format json`** and edit **`CHANGELOG.md`** in git diffs like any other source file.

```bash
python scripts/changelog_unreleased.py --check-nonempty
pip-audit -r requirements.txt  # example; use your org's scanner and inputs
```

### Beyond core: maintainer credits CLI and prose linters

Some forks want a **`replayt credits`** or **`replayt authors`** command that prints maintainer names or emails from the installed wheel. How author lists are formatted, whether emails belong in CI logs, and which metadata fields are authoritative vary by team, so replayt keeps people data in standard packaging metadata instead of a dedicated subcommand. Use **`replayt version --format json`**: under **`distribution_metadata`**, read **`summary`**, **`license`**, and sorted **`project_urls`** (from PEP 566 **`Project-URL`** headers) when **`ok`** is true, and fall back to **`pip show`** or **`importlib.metadata`** for **`Author`** / **`Author-email`** when you need a roster line.

```bash
replayt version --format json | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['distribution_metadata']['project_urls'], indent=2))"
pip show replayt
python -c "from importlib.metadata import metadata; m=metadata('replayt'); print(m.get('Author'), m.get_all('Author-email', []))"
```

Typo scanners (**`codespell`**, **`typos`**, **`cspell`**) and prose linters depend on locale, product names, and dictionary choices replayt cannot pick for every downstream repo. **`python scripts/maintainer_checks.py`** stays focused on version, changelog, docs index, and contract gates; add a separate CI job (or pre-commit entry) that runs your scanner against **`src`**, **`docs`**, and **`README.md`**.

```bash
pip install codespell
codespell src docs README.md
```

### Beyond core: hosted API reference from docstrings

Some forks want a **versioned browsable API** (Sphinx, MkDocs, **pdoc**, or Read the Docs) generated from **`src/replayt`**. replayt ships prose under **`docs/`** and a checked-in **`docs/PUBLIC_API_CONTRACT.json`** snapshot for semver-facing **`replayt.__all__`** drift, not a second documentation product inside the wheel. Run your generator against an editable or pinned install, publish the HTML from **your** CI, and keep linking **`RUN_LOG_SCHEMA.md`** from the same commit or tag consumers use for JSONL parsers.

```bash
pip install pdoc
python -m pdoc replayt --output-directory /tmp/replayt-apidocs
python scripts/public_api_report.py --check docs/PUBLIC_API_CONTRACT.json
```

### Beyond core: MCP servers wrap the CLI

**Model Context Protocol** hosts expect stable tool contracts, explicit argv, and parseable errors. replayt stays a **CLI + library**, not an MCP runtime: implement tools in **your** server that call **`replayt`** as a subprocess with a fixed allowlist (for example only **`inspect`**, **`runs`**, **`verify-seal`** in production). Cross-check allowlisted names against sorted **`cli_subcommands`** from the same JSON when you upgrade replayt. Use **`--output json`** / **`--format json`** and map **`schema`** fields to the ids advertised under **`cli_machine_readable_schemas`** from **`replayt version --format json`**. Read **`cli_json_stdout_contract`** from the same JSON when you need the exact flag shape per subcommand (for example **`contract`** uses **`--format json`**, while **`inspect`** also accepts **`--json`**). The same object includes **`subprocess_stream_semantics`**: one UTF-8 JSON object on stdout when a machine route is active, with stderr allowed to carry human hints (for example **`replayt ci`** always prints a one-line exit-code legend on stderr). Each JSON-on-stdout route includes a **`trust_profile`** id; resolve it against sibling **`trust_profiles`** to see whether that argv can append run logs, invoke **`run_hook`** or seal/verify hooks, write scaffold files (**`try --copy-to`**), or stay inventory-only when you split read tools from execute tools in the host. Read **`cli_stdio_contract`** from the same JSON: unless you intentionally pipe a UTF-8 JSON object for **`--inputs-file -`**, **`--inputs-json @-`**, or **`REPLAYT_INPUTS_FILE=-`**, pass **`stdin=subprocess.DEVNULL`** so the host's attached stdin does not become workflow inputs on **`run`**, **`ci`**, **`validate`**, or **`doctor`**. There is no generated OpenAPI or function-calling schema for every CLI flag; derive tool argv from **`--help`** and validate JSON payloads with **`cli_machine_readable_schemas`**. When you implement **`run_hook`**, **`resume_hook`**, or export/seal/verify hooks yourself, read **`policy_hook_env_catalog`** from the same JSON so your wrapper asserts the full set of injected **`REPLAYT_*`** names (optional keys may be absent on a given invocation) and matches **`subprocess_stdin`**: **`devnull`**. Respect exit codes: **`0`** success, **`1`** user or verification errors on read-only commands, **`2`** approval pause on **`replayt run`** / **`replayt ci`** / **`replayt resume`** / **`replayt try`**, and **`2`** when Typer rejects argv before any workflow runs (bad flags, missing args). **`cli_json_stdout_contract.typer_pre_dispatch_phase`** and **`cli_exit_codes.typer_pre_dispatch_failures`** document the overlap: with **`--output json`** on **`run` / `ci` / `try`**, a real pause prints **`replayt.run_result.v1`** with **`status`** **`paused`** on stdout; Typer parse failures usually leave stdout non-JSON so **`json.loads`** fails and stderr has the Usage / Error panel. **`replayt resume`** has no JSON-on-stdout mode; pauses still exit **`2`** after text lines such as **`status=paused`**. Compare Typer-only failures using stderr and whether runner output appeared (**`disambiguation_for_resume_text_stdout`** in the same contract object).

```bash
replayt version --format json | python -c "import json,sys; print(json.load(sys.stdin)['cli_machine_readable_schemas']['verify_seal_report'])"
```

```bash
replayt version --format json | python -c "import json,sys; d=json.load(sys.stdin)['policy_hook_env_catalog']['hooks']['run_hook']; print(d['argv_env'], len(d['injected_env_vars']))"
```

```bash
replayt version --format json | python -c "import json,sys; c=json.load(sys.stdin)['cli_stdio_contract']; print(c['recommended_subprocess_stdin'], c['reads_utf8_json_object_from_stdin']['subcommands'])"
```

```bash
replayt version --format json | python -c "import json,sys; d=json.load(sys.stdin)['cli_json_stdout_contract']['subcommands']['inspect']; print(d)"
```

```bash
replayt version --format json | python -c "import json,sys; c=json.load(sys.stdin)['cli_json_stdout_contract']; print([r['trust_profile'] for r in c['subcommands']['run']])"
```

```bash
replayt version --format json | python -c "import json,sys; print(json.load(sys.stdin)['cli_json_stdout_contract']['subprocess_stream_semantics']['stdout']['encoding'])"
```

```bash
replayt version --format json | python -c "import json,sys; print(json.load(sys.stdin)['cli_json_stdout_contract']['typer_pre_dispatch_phase']['typical_exit_code'])"
```

```bash
# Example: fail CI if an allowlisted inspect tool forgets --output json (requires jq).
replayt version --format json | jq -e '.cli_json_stdout_contract.subcommands.inspect | map(select(.schema_key=="inspect_report")) | length > 0' >/dev/null
```

```python
import json
import subprocess

def tool_inspect_run(run_id: str) -> dict:
    proc = subprocess.run(
        ["replayt", "inspect", run_id, "--output", "json"],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    data = json.loads(proc.stdout)
    assert data.get("schema") == "replayt.inspect_report.v1"
    return data
```

For raw JSONL reads (no subprocess), open **`.replayt/runs/<run_id>.jsonl`** read-only and parse line-delimited JSON; see **Pattern: approval bridge** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md).

### Beyond core: shell completion and CLI discovery for wrappers

replayt keeps Typer **`add_completion=False`**, so there is no bundled **`replayt completion`** subcommand or **`--install-completion`** wiring in core: shells, path policy, and completion style vary by team. Add fish/bash/zsh snippets or Typer completion hooks **beside your repo** if you want tab completion for **`python -m replayt`**.

For argv allowlists and doc drift checks without scraping **`--help`**, read sorted **`cli_subcommands`** from **`replayt version --format json`** (top-level command names registered on the installed CLI). When Typer prints **No such command**, open **`replayt --help`** or print that JSON list instead of expecting fuzzy **"did you mean …"** spelling correction inside core. replayt does **not** ship **`replayt --help --format json`** or a full per-command flag schema; use **`replayt <cmd> --help`** from a dev-only codegen step, or introspect Click/Typer in **your** tooling when you need every option spelled out.

```bash
replayt version --format json | python -c "import json,sys; print(json.load(sys.stdin)['cli_subcommands'])"
```

### Beyond core: skill-release loop wrappers and sidecar integrity

Maintainer **`scripts/skill_release_loop.py`** (and **`skill_release_loop_agent.py`**) export **`SKILL_*`** environment variables and write **`replayt.skill_invocation.v1`** JSON beside each generated **`*.prompt.md`**; see **Automated skill-loop release** in [`CONTRIBUTING.md`](../../CONTRIBUTING.md). **`replayt version --format json`** includes **`skill_loop_env_contract`** (`replayt.skill_loop_env_contract.v1`) with **`main_injected_env`** and **`fix_injected_env`** rows (**`name`**, **`description`**) for the same variable names the loop sets on subprocesses (fix steps omit **`SKILL_PATH`** / **`SKILL_REQUESTED_NAME`**). Sidecars and the environment include repo-relative paths (**`SKILL_PROMPT_REL`**, **`SKILL_LOG_REL`**, **`SKILL_RUN_DIR_REL`**) plus **`SKILL_COMMAND_SHA256`** (SHA-256 of the raw **`--skill-command`** template) and **`SKILL_TASK_SHA256`** (SHA-256 of the outer **`--task`** string), mirrored as **`skill_command_sha256`** and **`task_sha256`** in JSON and in **`pipeline.json`**. The first skill step writes **`pipeline.json`** (**`replayt.skill_release_pipeline.v1`**) with ordered skill names, **`pipeline_sha256`**, **`skill_command_sha256`**, and **`task_sha256`**. **`--resume`** refuses to continue if **`--skills`** order drifts, if the stored **`skill_command_sha256`** disagrees with the current template, or if **`task_sha256`** disagrees with the current **`--task`** (older **`pipeline.json`** files that omit either digest field still skip only that check). replayt does not auto-inject a parent run directory for nested loops or add a **`prompt_sha256`** field on every sidecar: only your outer harness knows whether a run is nested, and hashing prompts is a one-liner when you need it.

```bash
INV=iter-01-demo.invocation.json
PROMPT=$(jq -r '.prompt_file' "$INV")
test -f "$PROMPT"
shasum -a 256 "$PROMPT"
jq -r '.pipeline_sha256' "$INV"
jq -r '.skill_command_sha256' "$INV"
jq -r '.task_sha256' "$INV"
replayt version --format json | jq '.skill_loop_env_contract.main_injected_env[].name'
```

Export **`PARENT_SKILL_RUN_DIR`** (or similar) from **your** wrapper before invoking the loop a second time, and mention it inside **`--task`** so agents and logs stay explicit.

## Beyond core: streaming, hooks, approvals, and logs

### Beyond core: policy profiles and cloud upload from hooks

Some teams want **dev / staging / prod**-specific **`run_hook`** commands or a **one-line upload** after **`export-run`** writes a tarball. replayt does not add **`policy_profile`** keys or **`--upload-uri`** flags: merge order between TOML and env would hide which gate ran, and cloud SDK pins belong in **your** image. Use a CI matrix (or wrapper exports) so **`REPLAYT_RUN_HOOK`** / **`REPLAYT_EXPORT_HOOK`** points at the right script per environment, and read **`REPLAYT_REPLAYT_VERSION`** when the script must reject older CLIs. After **`export_hook`** runs, replayt still writes the archive to **`REPLAYT_EXPORT_OUT`**; copy it with tooling you already operate:

```bash
aws s3 cp "$REPLAYT_EXPORT_OUT" "s3://audit-bucket/replayt/$(basename "$REPLAYT_EXPORT_OUT")"
```

The same pattern applies to standalone **`replayt seal`** via **`REPLAYT_SEAL_OUT`**.

### Beyond core: LLM gateway allowlists and inline JSONL hash chains

Some reviews ask for a **hostname allowlist** on **`OPENAI_BASE_URL`** or a **hash chain** embedded in every JSONL line. Corporate gateways, air-gap rules, and Merkle semantics differ by tenant, and mutating the event schema would break stable **`RUN_LOG_SCHEMA.md`** consumers. Keep **`LLMBridge`** on the shared OpenAI-compat path; gate egress in **`run_hook`** (or **`resume_hook`**) by reading **`OPENAI_BASE_URL`** from the environment your wrapper exports, or enforce the policy at your HTTP proxy. For tamper evidence, use **`replayt seal`**, **`replayt verify-seal`**, and optional **`seal_hook`** / **`export_hook`** wrappers that sign or upload artifacts replayt already wrote.

```bash
python -c "import os, urllib.parse as u; h=u.urlparse(os.environ.get('OPENAI_BASE_URL','')).hostname; assert h in {'llm.corp.example'}, h"
```

replayt keeps explicit states, append-only **JSONL**, and structured LLM outputs. Use **`ctx.llm.with_settings(...)`** for per-call overrides; they show up under **`effective`** on **`llm_request`** events. Core does **not** log per-token streams because that is too noisy for replay. Stream inside a step, then store a **Pydantic-validated** result or a short summary. **`replayt resume`** covers many approval flows; richer UIs can read the same JSONL and resolve gates in **your** app. Notifications, trace IDs, and policy hooks belong in wrappers or callbacks. If you need stronger audit handoff, hash, encrypt, or archive **your** logs; the runtime cannot prove integrity if an attacker can write the log directory (see **Security and trust boundaries** in [`README.md`](../../README.md)).

### Beyond core: clean git trees and LLM spend gates

Some compliance checks want a **clean git working tree** before a model is called, or a **hard stop** when estimated LLM spend crosses a budget. Submodule rules, generated files, and billing math differ per repository and provider account, so replayt does not embed **`git`** or ledger logic in **`Runner.run`**. Use a **`run_hook`** (or a CI job that runs before **`replayt ci`**) to enforce the policy you mean: fail fast when porcelain status is non-empty, or when **`jq`** / DuckDB totals over past **`llm_response`** lines exceed a threshold you compute externally.

```bash
test -z "$(git status --porcelain)" || { echo "dirty tree"; exit 1; }
replayt ci TARGET --summary-json summary.json
```

Pass stable budget or ticket metadata through **`--metadata-json`** / **`--tag`** so the hook can read **`REPLAYT_RUN_METADATA_JSON`** and **`REPLAYT_RUN_TAGS_JSON`** without guessing from the shell alone (see **CLI policy subprocesses** in [`README.md`](../../README.md)).

### Beyond core: failure banners and spreadsheet-style run lists

Stakeholders sometimes want **`replayt run`** to print a **copy-paste report command** on stderr whenever a workflow fails, or a **CSV** of recent runs for spreadsheets. Wording, locale, and which columns matter change per team, so the CLI does not add a second human-facing narrative on top of normal exit codes and JSONL. Wrap **`replayt run`** / **`replayt ci`** in a shell script or use **`run_hook`** to echo **`replayt report "$RUN_ID" --style stakeholder`** (or **`replayt replay … --style stakeholder`**) when **`$?`** is **`1`**, and keep notifications in **your** layer (**Pattern: webhook / lifecycle callbacks** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md)). For tabular exports, reshape **`replayt runs --output json`** with **`jq`** instead of a bundled CSV schema:

```bash
replayt runs --log-dir .replayt/runs --output json | jq -r '.runs[] | [.run_id, .status] | @csv'
```

### Beyond core: PDF rendering and wiki uploads

**`replayt report`** already emits self-contained HTML or Markdown (**`--format`**, **`--style stakeholder`**). Legal and PM handoffs sometimes want PDFs or a Confluence/Notion page. PDF engines, fonts, headers, and headless browser pins differ by team, and each wiki has its own OAuth, space keys, and retention rules. Keep replayt local-first: write the report to disk, then convert or upload in **your** CI or desktop toolchain. Treat **`bundle-export`** tarballs as the canonical audit bundle and link them from the wiki if policy allows.

```bash
replayt report "$RUN_ID" --style stakeholder --out report.html
# Print report.html to PDF from a browser, Chromium --print-to-pdf, or a container image you maintain.
```

### Beyond core: logprobs and vendor-only chat fields

Some ML workflows need **token logprobs**, OpenAI **`user`** / **`service_tier`**, or other **vendor-specific JSON** keys on **`/chat/completions`**. replayt keeps **`LLMBridge`** on a small shared schema so logs stay replay-friendly; stuffing full **`logprobs`** blobs into **`llm_response`** would dwarf the rest of the timeline. Call the **official client inside one step**, inspect likelihoods or headers there, and only persist what you need: either **`ctx.set`** / **`structured_output`** for structured summaries or **`ctx.note`** for a short scalar breadcrumb. The same pattern covers **`user`** strings for abuse tracking: the OpenAI Python SDK accepts them on the create call while replayt still owns transitions and approvals.

```python
from openai import OpenAI

@wf.step("sdk_extras")
def sdk_extras(ctx):
    client = OpenAI()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "ping"}],
        user="replayt-run-" + ctx.run_id,
        logprobs=True,
        top_logprobs=2,
    )
    ctx.note("llm_calibration", summary="top_logprobs captured in-process", data={"finish": r.choices[0].finish_reason})
    ctx.set("answer", r.choices[0].message.content or "")
    return "done"
```

See **Pattern: OpenAI Python SDK inside a step** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md) for the full shape.

### Beyond core: logit_bias, schema codegen, and parse contracts

**`logit_bias`** and other token-index maps are the same boundary as logprobs: keep **`LLMBridge`** on the shared OpenAI-compat surface. When your proxy accepts them, attach a small JSON object via **`ctx.llm.with_settings(..., extra_body={"logit_bias": {...}})`** so the values still appear under **`effective`**; otherwise call the vendor SDK inside one step (**Beyond core: logprobs and vendor-only chat fields** above). For structured outputs, replayt does **not** infer schemas from arbitrary example JSON inside **`parse`**; ship an explicit **`class Out(BaseModel): ...`** (hand-written or generated once) so reviewers can diff contracts in git. A common one-off is to generate models from JSON Schema you already trust:

```bash
datamodel-codegen --input schema.json --output mymodels.py
```

**Composition patterns** (copy the names into EXAMPLES_PATTERNS search):

- **Pattern: stream inside step, log structured summary**: streaming UX without core token events.
- **Pattern: approval bridge (local UI)**: web or chat approvals while replayt stays the engine.
- **Pattern: webhook / lifecycle callbacks**: notifications and policy hooks without turning core into an observability platform.
- **Pattern: encrypted run logs** and **Pattern: post-hoc PII scrub on JSONL files**: tighter disk handling and redaction.

### Beyond core: public pastebins and bundled approval UIs

**replayt** does not ship **`replayt paste-run`** (or similar) that uploads JSONL to a public paste service or anonymous file share. Raw timelines can still hold prompts, tool arguments, and PII even under **`LogMode.redacted`**. For tickets or chat, prefer **`replayt report RUN_ID --format markdown --style support`**, stakeholder **`replayt replay … --format html`**, or **`replayt bundle-export`** and an internal handoff path your security team accepts. Core also does not bundle a runnable FastAPI/Flask approval server beside the wheel; routing, auth, and hosting belong in **your** repo (**Pattern: approval bridge (local UI)** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md)).

Share a read-only timeline for review without building a server (add **`--style stakeholder`** or **`support`** to drop **`llm_*`** / **`tool_*`** rows and match **`replayt report`** handoffs):

```bash
replayt replay <run_id> --format html --style stakeholder --out run.html
```

**Markdown run summary** (paste into tickets or chat; same **`--style`** rules as HTML). Paused runs include a copy-paste **`replayt resume TARGET …`** line; replace **`TARGET`** with your **`module:wf`** or workflow path.

```bash
replayt report <run_id> --format markdown --style support --out handoff.md
```

**Two-run comparison:** **`replayt report-diff RUN_A RUN_B`** defaults to HTML; add **`--format markdown`** when you need the same stakeholder sections (metadata, failures, structured outputs, approvals) as pasteable text. With **`--style stakeholder`** or **`support`**, the document ends with **Stakeholder CLI handoff** copy-paste lines (regenerate this comparison, **`replayt diff … --output json`**, per-run **`inspect`** / stakeholder **`report`** / offline **`replay`**, JSON **`inspect`** when a side failed, and **`resume`** hints per paused run), aligned with **`replayt report`**. For automation, use **`replayt diff RUN_A RUN_B --output json`** instead of a parallel JSON report-diff schema.

```bash
replayt report-diff <run_a> <run_b> --format markdown --out compare.md
replayt diff <run_a> <run_b> --output json
```

**`bundle-export`** still ships **`report.html`** only; generate **`.md`** in CI with **`--format markdown`** when your process wants both.

Optional **line/file SHA-256 manifest** for a JSONL run (extra audit packet, not proof against someone who can edit the log dir):

```bash
replayt seal <run_id>
replayt verify-seal <run_id>
```

After **`bundle-export --seal`**, extract **`events.jsonl`** and **`events.seal.json`** and check them without re-running export:

```bash
replayt verify-seal <run_id> --manifest path/to/events.seal.json --jsonl path/to/events.jsonl
```

Org policy can attach a **`verify_seal_hook`** (or **`REPLAYT_VERIFY_SEAL_HOOK`**) so CI logs to an internal audit index or checks a ticket only after digests match; see **`verify_seal_hook`** in [`docs/CONFIG.md`](../../docs/CONFIG.md).

For **cryptographic signing** (GPG, minisign, Sigstore), keep that in **your** release or compliance pipeline: sign the manifest bytes (or the tarball) after **`replayt seal`** / export; replayt stays a local runner, not a key-management product.

For **in-process** trace IDs or policy logging, use **`Runner(..., before_step=..., after_step=...)`** in Python (see **Pattern: webhook / lifecycle callbacks** for outer-wrapper alternatives).

### Framework-style agents, streaming, and planner loops (feature 10 / composition)

replayt keeps **explicit** states and append-only JSONL. Per-token log lines and hidden planners are out of scope ([**docs/SCOPE.md**](../../docs/SCOPE.md)). The supported shape is simple: **one step** wraps the other SDK or graph, and **one** validated exit shape picks the next state.

### LangGraph (and similar frameworks): **composition**, not core

replayt will not ship LangGraph inside the runner because that would hide control flow next to an explicit FSM (see the **LangChain / LangGraph** row in **[docs/SCOPE.md](../../docs/SCOPE.md)**). The supported shape is to run LangGraph **inside one `@wf.step`**, then move replayt forward from **one** Pydantic-shaped outcome (or a small summary you write to context). Stream tokens and run planner loops **inside** that handler; log the **final** structured data via `ctx.llm.parse(...)`, `structured_output` events, tools, or a small `ctx.note(...)` breadcrumb, not every planner tick. When you call the OpenAI-style chat API with native `tool_calls` in that sandbox, **`ctx.tools.openai_chat_tools()`** mirrors your **`@ctx.tools.register`** handlers into the vendor `tools=` list; still execute each call with **`ctx.tools.call`** so JSONL keeps typed **`tool_call`** / **`tool_result`** lines (**Sub-pattern: OpenAI `tools=` from `ctx.tools`** in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)**).

Install graph libraries in **your** project only:

```bash
pip install langgraph langchain-core
```

Example pattern (adapt imports and graph build to your codebase):

```python
from pydantic import BaseModel

class AgentChunkOut(BaseModel):
    answer: str
    route: str

@wf.step("with_langgraph")
def with_langgraph(ctx):
    from langgraph.graph import StateGraph  # type: ignore[import-untyped]

    # graph = ... build StateGraph, .compile(), etc.
    # result = graph.invoke({"messages": ctx.get("messages", [])})
    result = {"answer": "stub", "route": "done"}  # replace with real invoke()
    out = AgentChunkOut.model_validate(
        {"answer": str(result.get("answer", ""))[:4000], "route": str(result.get("route", "done"))}
    )
    ctx.note("framework_summary", summary="sandbox graph completed", data={"provider": "langgraph"})
    ctx.set("last_agent", out.model_dump())
    return out.route if out.route in {"done", "retry"} else "done"
```

Human gates stay replayt-native: **`ctx.request_approval`** or the **Pattern: approval bridge** in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)**.

### Finding runs that used a typed tool

Each **`ctx.tools.call(...)`** still emits normal **`tool_call`** / **`tool_result`** lines. To list local runs that invoked a particular registered tool (for example after wrapping LangChain tool nodes in one sandbox step), filter by exact tool name:

```bash
replayt runs --tool search_repo --tool fetch_url --limit 50
```

Use **`replayt inspect RUN_ID --tool search_repo`** (repeat for OR) to list only matching **`tool_call`** lines from one run, or **`--event-type tool_call`** when you want every tool invocation regardless of name.

### Finding runs that logged a structured output schema

**`ctx.llm.parse(...)`** and similar paths emit **`structured_output`** (or **`structured_output_failed`**) with a payload **`schema_name`** that matches your Pydantic model class name. Freeform **`ctx.llm.complete_text(..., schema_name="DraftRaw")`** tags the paired **`llm_request`** / **`llm_response`** lines with the same field (no **`schema_sha256`**; you parse prose yourself). Filter recent runs the same way as **`--tool`**:

```bash
replayt runs --structured-schema Decision --structured-schema Plan --limit 50
replayt stats --structured-schema Decision --output json
replayt inspect RUN_ID --structured-schema Decision --structured-schema Plan --output json
```

Use **`replayt inspect RUN_ID --structured-schema MyModel`** (repeat for OR) when you want matching **`structured_output`** / **`structured_output_failed`** lines and any tagged **`llm_request`** / **`llm_response`** pairs, or **`--event-type structured_output`** (and repeat **`--event-type structured_output_failed`** if you need both event types regardless of **`schema_name`**).

Each successful **`structured_output`** line also carries the full **`effective`** object (same shape as on **`llm_request`**), plus **`usage`**, **`latency_ms`**, and **`finish_reason`** copied from the same completion as the preceding **`llm_response`**, so cost or latency rollups keyed by **`schema_name`**, or filters on **`model`** / **`experiment`**, do not need a second join. The matching **`llm_request`** / **`llm_response`** pair from **`ctx.llm.parse(...)`** repeats the same **`schema_name`** (and **`schema_sha256`**) as the structured lines, so you can attribute token **`usage`** to a contract as soon as the provider returns, even when a parse later fails and only **`structured_output_failed`** is written. Example: `jq 'select(.type=="structured_output") | .payload | {schema_name, effective, usage, latency_ms}' run.jsonl` (or **`duckdb`** over **`read_json_auto`** per **Pattern: DuckDB ad-hoc analytics** in [`docs/EXAMPLES_PATTERNS.md`](../../docs/EXAMPLES_PATTERNS.md)).

### Multiple LLM calls in one handler (`call_label`)

When one **`@wf.step`** runs several **`ctx.llm.parse`** or **`complete_text`** round trips (for example draft vs critic), reuse **`schema_name`** alone may not distinguish them if both use the same Pydantic contract. Set a short per-bridge tag with **`ctx.llm.with_settings(call_label="critic")`** so JSONL rows include **`payload.call_label`** and **`payload.effective.call_label`** (same string; capped at 128 characters after strip). This is **not** a framework or adapter label and does not replace run-level **`experiment`** cohort tags.

```python
draft = ctx.llm.with_settings(call_label="draft").parse(Plan, messages=[...])
critique = ctx.llm.with_settings(call_label="critic").parse(Review, messages=[...])
```

```bash
jq 'select(.type=="llm_response" and .payload.call_label=="critic")' run.jsonl
```

### Beyond core: embeddings outside chat completions

replayt's **`LLMBridge`** stays on **`/v1/chat/completions`**. **Embeddings** use a different path and response shape, so call **`httpx`**, **`openai.OpenAI().embeddings.create(...)`**, or your vendor SDK **inside one `@wf.step`**, then store vectors or ids on **`ctx`** (or emit a small **`ctx.note`** if the log needs a breadcrumb). Keep the heavy tensor payloads out of JSONL unless your policy explicitly wants them.

```python
# Illustrative: embeddings live in the step, not on LLMBridge.
from openai import OpenAI

@wf.step("embed")
def embed_step(ctx):
    client = OpenAI()
    vec = client.embeddings.create(model="text-embedding-3-small", input=ctx.get("text", "")).data[0].embedding
    ctx.set("embedding_dim", len(vec))
    ctx.note("embedding_ok", summary="computed embedding", data={"dim": len(vec)})
    return "next"
```

### `experiment` tags vs model routing

Use **`experiment={...}`** (or **`--experiment-json`** on the CLI) for **analytics and cohort labels** in JSONL, not as a hidden switch that picks models or gateways inside replayt core. Choosing **`model`**, **`provider`**, or **`base_url`** from metadata without an explicit branch in your step would blur control flow and complicate audits. Keep cohorts in **`experiment`** for **`jq` / DuckDB**, and select the model in code (often via **`ctx.llm.with_settings(...)`**) so **`effective.model`** always matches a reviewed code path.

```python
cohort = str(ctx.get("cohort", "a"))
bridge = ctx.llm.with_settings(
    model="gpt-4o-mini" if cohort == "b" else "gpt-4o",
    experiment={"cohort": cohort},
)
decision = bridge.parse(Decision, messages=[{"role": "user", "content": "..."}])
```

```bash
jq 'select(.type=="llm_response" and .payload.schema_name=="Decision") | .payload | {model: .effective.model, usage, experiment: .effective.experiment}' run.jsonl
```

### Finding runs by logged model id

When you A/B models or pin different gateways per environment, the canonical id is on **`llm_request`**, **`llm_response`**, and structured-output lines (**`effective.model`**, with a legacy fallback to top-level **`model`**). Filter the same way as **`--tool`** and **`--structured-schema`** (repeat for OR; AND across different filter families):

```bash
replayt runs --llm-model gpt-4o-mini --llm-model claude-3-5-sonnet-20241022 --limit 50
replayt stats --llm-model gpt-4o-mini --output json
replayt inspect RUN_ID --llm-model gpt-4o-mini --output json
replayt report RUN_ID --llm-model gpt-4o-mini --format markdown
replayt diff RUN_A RUN_B --llm-model gpt-4o-mini --output json
replayt report-diff RUN_A RUN_B --llm-model gpt-4o-mini
```

### Finding runs by LLM `finish_reason`

OpenAI-compatible **`llm_response`** lines include **`finish_reason`** (for example **`stop`** vs **`length`**). That is the quickest signal when an agent-style step keeps running out of tokens. List recent runs or narrow one timeline the same way as **`--tool`** (repeat the flag for OR):

```bash
replayt runs --finish-reason length --limit 50
replayt inspect RUN_ID --finish-reason length --output json
```

Pair with **`--event-type llm_response`** when you want matching responses alongside other event types (same rules as **`--note-kind`**).

### Finding framework breadcrumbs from `ctx.note(...)`

If your sandbox step emits explicit **`ctx.note(...)`** breadcrumbs such as **`framework_summary`** or **`subrun_link`**, filter by the note kind instead of grepping JSONL:

```bash
replayt runs --note-kind framework_summary --limit 50
replayt inspect RUN_ID --note-kind framework_summary
```

That matches replayt's explicit event model: one framework-shaped breadcrumb in the log, not framework-owned control flow in the runner.

### Beyond core: Instructor-style parsers and DSPy-style compiled programs in core

Some teams want **Instructor**, **PydanticAI**, or **DSPy** `compile` flows to own retries, optimizers, or prompt templates. replayt does not ship those as **`LLMBridge`** backends or optional dependencies: their retry and compilation policies would fight replayt's explicit step boundaries and bloat the wheel. Call them **inside one `@wf.step`**, validate to **one** Pydantic object (or tag a freeform completion with **`ctx.llm.complete_text(..., schema_name="…")`**), then **`return "next_state"`** so transitions stay in your code (**Pattern: framework in a sandbox step** in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)**). For listing runs that only used a labeled freeform bridge call, **`replayt runs --structured-schema YourLabel`** matches the **`llm_request`** / **`llm_response`** pair when you passed **`schema_name=`**.

### Beyond core: graph checkpoints and model-driven multi-tool turns

replayt does not import LangGraph **checkpoints** or thread blobs into the parent JSONL timeline; keep checkpoints inside the graph library and persist **one** validated exit shape to replayt context (see **Pattern: workflow composition via explicit sub-run** in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)** when you need a separate child **`run_id`**). The runtime also does not fan out a single model **`tool_calls` array** into parallel replayt states because that would hide scheduling order. Execute tool calls in a deterministic order inside the handler, then transition explicitly:

```python
for spec in tool_calls_from_model:
    ctx.tools.call(spec["name"], spec["arguments"])
```

## 1. Hello world - `replayt_examples.e01_hello_world`

Start here for the smallest replayt workflow.

### What the code does

This example has only two states: `greet` and `done`.

- `greet` reads `customer_name` from context.
- It writes `message` and `next_action` back into context.
- It transitions directly to `done`.
- `done` sets `completed=true` and returns `None`, which ends the workflow.

Use this example to learn the core replayt model: a named state reads context, writes context, and returns the next state explicitly.

### What to run
The smallest workflow in the tutorial set. It writes a greeting and a next action into context so you can inspect and replay the run.

With the sample input, the run should finish successfully and the final context should include `message="Hello, Sam! Your first replayt workflow ran."`, `next_action="Inspect this run, then replay it from the CLI."`, and `completed=true`.

```bash
replayt run replayt_examples.e01_hello_world:wf \
  --inputs-json '{"customer_name":"Sam"}'
```

Then inspect what happened:

```bash
replayt inspect <run_id>
replayt replay <run_id>
```

### What to expect

The run should complete successfully in a very small number of events. The final context should include:

- `message="Hello, Sam! Your first replayt workflow ran."`
- `next_action="Inspect this run, then replay it from the CLI."`
- `completed=true`

## 2. Intake normalization - `replayt_examples.e02_intake_normalization`

This example uses a common workflow pattern: validate raw input first, then transform it into a cleaner internal representation.

### What the code does

The workflow has three stages, but only two state handlers do real work:

- `validate` checks that `lead` exists and matches the `RawLead` Pydantic schema.
- `normalize` trims whitespace, title-cases the name, lowercases the email, compresses message spacing, and derives a `segment`.
- `done` ends the run.

Deterministic steps you want to inspect later do not need an LLM; they use the same run log and replay model.

### What to run
Validate a raw lead payload, normalize formatting, and derive an internal segment.

With the sample input, the run should finish successfully and store `normalized_lead` with `name="Sam Patel"`, `email="sam@example.com"`, `company="Northwind"`, a whitespace-normalized message, and `segment="enterprise"` because the sample message mentions a demo for many seats.

```bash
replayt run replayt_examples.e02_intake_normalization:wf \
  --inputs-json '{"lead":{"name":"  Sam Patel ","email":"SAM@example.com ","company":"Northwind","message":"Need a demo for 40 seats"}}'
```

### What to expect

The run should complete successfully and preserve both the validated input and the normalized output in context. In particular, `normalized_lead` should contain:

- `name="Sam Patel"`
- `email="sam@example.com"`
- `company="Northwind"`
- `message="Need a demo for 40 seats"`
- `segment="enterprise"`

The `segment` becomes `enterprise` because the normalization logic checks whether the message mentions `seat` or `demo`. That is deterministic branching from explicit code, not a model guess.

## 3. Support routing - `replayt_examples.e03_support_routing`

This example shows explicit branching for operational workflows.

### What the code does

The workflow validates the incoming `ticket`, then derives a routing decision from plain rules:

- security keywords route to the `security` queue with `urgent` priority
- billing keywords route to the `billing` queue
- bug/error keywords route to the `technical` queue
- enterprise or VIP customers can raise the priority even if the queue stays the same

Finally, the workflow writes a `routing_decision` dictionary with queue, priority, and SLA hours.

### What to run
A deterministic branching flow for support operations.

With the sample input, the run should finish successfully and write `routing_decision` with `queue="billing"`, `priority="high"`, and `sla_hours=4` because the ticket mentions payment failure and the customer tier is `enterprise`.

```bash
replayt run replayt_examples.e03_support_routing:wf \
  --inputs-json '{"ticket":{"channel":"email","subject":"Payment failed twice","body":"Enterprise invoice card was declined during renewal.","customer_tier":"enterprise"}}'
```

### What to expect

The sample input contains billing language (`payment`, `invoice`, `declined`) and an enterprise customer tier. That means the final `routing_decision` should be:

- `queue="billing"`
- `priority="high"`
- `sla_hours=4`

Change the subject or body and the route should shift in predictable ways.

## 4. Typed tool calls - `replayt_examples.e04_tool_using_procurement`

This example introduces replayt's typed tool system.

### What the code does

Inside the `intake` step, the workflow registers two tools:

- `calculate_total(unit_price, quantity)` computes the purchase total
- `budget_policy(query: BudgetPolicyInput)` checks the department's spending limit

After validating the purchase request, the `evaluate` step calls those tools through `ctx.tools.call(...)` rather than invoking ad hoc helper functions. That means the tool activity is captured in the run history.

### What to run
Register strongly typed tools and use them from a workflow step.

With the sample input, the run should finish successfully, the event log should show typed calls to `calculate_total` and `budget_policy`, and the final `decision` should record `total_cost=298.0`, `within_policy=true`, and `recommended_action="auto_approve"` for the Design request.

```bash
replayt run replayt_examples.e04_tool_using_procurement:wf \
  --inputs-json '{"request":{"employee":"Maya","department":"Design","item":"monitor arm","unit_price":149.0,"quantity":2}}'
```

### What to expect

The run should complete successfully and the event log should show both tool call and tool result events. In final context, `decision` should look roughly like this:

- `employee="Maya"`
- `item="monitor arm"`
- `total_cost=298.0`
- `within_policy=true`
- `recommended_action="auto_approve"`

The Design department limit in the example code is `500.0`, so a total of `298.0` stays within policy. The same run covers typed tools and deterministic post-tool branching.

## 5. Retries for flaky integrations - `replayt_examples.e05_retrying_vendor_lookup`

This example shows explicit retries that stay visible in the run history.

### What the code does

The `lookup` step is decorated with a retry policy of up to three attempts. The implementation simulates a flaky dependency:

- it increments `lookup_attempts`
- it throws a temporary error on the first attempt
- it succeeds on the second attempt by storing `vendor_record`

The `summarize` step then copies the vendor record into `lookup_summary` and includes the attempt count.

### What to run
Show how a state can retry automatically before succeeding.

With the sample input, the first `lookup` attempt should fail with a temporary timeout, replayt should retry automatically, and the second attempt should succeed. `lookup_summary` should end with `vendor_name="Acme Fulfillment"`, `status="active"`, `payment_terms="net-30"`, `risk_level="low"`, and `lookup_attempts=2`.

```bash
replayt run replayt_examples.e05_retrying_vendor_lookup:wf \
  --inputs-json '{"vendor_name":"Acme Fulfillment"}'
```

### What to expect

You should see a failed `lookup` attempt followed by an automatic retry and then a successful continuation into `summarize`. The final `lookup_summary` should include:

- `vendor_name="Acme Fulfillment"`
- `status="active"`
- `payment_terms="net-30"`
- `risk_level="low"`
- `lookup_attempts=2`

Retries are visible and auditable: replayt records the failed attempt in the workflow history instead of hiding it.

## 6. Sales call prep brief - `replayt_examples.e06_sales_call_brief`

This is the first example where the model produces a structured object.

### What the code does

The workflow defines a `CallBrief` schema with these fields:

- `customer_stage`
- `top_goals`
- `risks`
- `recommended_talking_points`
- `next_step`

The single working state, `draft_brief`, sends the account name and CRM notes to `ctx.llm.parse(...)`. replayt then validates the model output against the schema before storing it in context as `call_brief`.

### What to run
Use structured LLM output to turn CRM notes into a call brief.

With the sample input, the run should finish successfully and `call_brief` should validate against the `CallBrief` schema, so `inspect` shows structured fields such as `customer_stage`, `top_goals`, `risks`, `recommended_talking_points`, and `next_step`.

```bash
replayt run replayt_examples.e06_sales_call_brief:wf \
  --inputs-json '{"account_name":"Northwind Health","notes":"Champion wants SOC 2 confirmation, budget approved, pilot starts in April."}'
```

### What to expect

The exact wording will vary by model, but the outcome should still be predictable in shape. The run should complete successfully and `call_brief` should always be a schema-valid object rather than raw free-form text. In practice you should expect:

- a `customer_stage` consistent with active evaluation or procurement
- goals related to the pilot and security review
- risks related to SOC 2 confirmation or rollout timing
- talking points for the next conversation
- a concise `next_step`

The output stays structured, so you can use it in the next step.

## 7. Customer feedback clustering - `replayt_examples.e07_feedback_clustering`

This example scales the same structured-output idea to a list of inputs instead of one note.

### What the code does

The workflow defines two schemas:

- `FeedbackTheme`, which captures one theme, its priority, supporting quotes, and a recommended owner
- `FeedbackSummary`, which collects all themes and a `release_note_hint`

The `cluster` step passes the whole feedback list to the model and asks for a structured summary.

### What to run
Use the LLM for batch summarization and prioritization.

With the sample input, the run should finish successfully and `feedback_summary` should contain a schema-validated list of themes plus a `release_note_hint`. Expect themes around exports or performance and identity access (Okta SSO), each with priorities and suggested owners.

```bash
replayt run replayt_examples.e07_feedback_clustering:wf \
  --inputs-json '{"product":"analytics dashboard","feedback":["Export to CSV times out on big reports.","Need SSO for Okta.","Dashboard is slow on Mondays."]}'
```

### What to expect

Model wording will vary, but the structure should stay stable. `feedback_summary` should contain:

- a list of themes in `themes`
- for each theme, a `priority`, `representative_quotes`, and `recommended_owner`
- a single `release_note_hint`

For this sample input, expect themes around performance or exports and around access or SSO. That is how replayt records structured analysis across several text inputs.

## 8. Travel approval - `replayt_examples.e08_travel_approval`

This example introduces a human approval gate.

### What the code does

The workflow has three important phases:

- `policy_check` validates the trip request and computes policy flags
- `manager_review` either auto-approves, pauses for approval, or routes to rejection based on approval state
- `book_trip` and `reject_trip` write the final status

The sample input is chosen to trigger review because it violates two simple policy checks: high estimated cost and short notice.

### What to run
Evaluate travel policy automatically, then pause for manager approval only when policy flags require it.

With the sample input, the run should pause with exit code 2 after `policy_check` stores `policy_flags=["high_cost", "late_notice"]` and requests `manager_review`. After approval it should finish with `travel_status="approved_for_booking"`, and after rejection it should finish with `travel_status="rejected"`.

```bash
replayt run replayt_examples.e08_travel_approval:wf \
  --inputs-json '{"trip":{"employee":"Sam Patel","destination":"New York","reason":"Customer onsite kickoff","estimated_cost":3200.0,"days_notice":5}}'
```

Approve it:

```bash
replayt resume replayt_examples.e08_travel_approval:wf <run_id> --approval manager_review
```

Reject it instead:

```bash
replayt resume replayt_examples.e08_travel_approval:wf <run_id> --approval manager_review --reject
```

### What to expect

On the first run, replayt should pause with exit code `2`. Before it pauses, the workflow should store:

- `travel_policy.auto_approvable=false`
- `travel_policy.policy_flags=["high_cost", "late_notice"]`

It then requests approval `manager_review` with a summary that includes the employee, destination, and flags.

If you approve the run, it should resume through `book_trip` and end with `travel_status="approved_for_booking"`.

If you reject the run, it should resume through `reject_trip` and end with `travel_status="rejected"`.

## 9. Incident response - `replayt_examples.e09_incident_response`

This example combines typed tools, deterministic severity logic, and an approval gate.

### What the code does

The workflow proceeds through four conceptual stages:

- `assess` validates the incident and assigns severity from the error rate
- `stabilize` uses tools to page on-call staff and draft a status page update
- `exec_review` decides whether external communications require approval
- `announce` or `internal_only` records the final communication plan

For sev1 incidents, the workflow pauses for an executive communications decision. Lower-severity incidents skip that approval path.

### What to run
Combine typed tools with an executive approval gate for sev1 communications.

With the sample input, the incident should be classified as `sev1` because `error_rate=12.5`. The run should log tool calls for paging and status-page draft creation, then pause for `exec_comms`; approving should resume to `communication_plan="external_statuspage_and_internal_slack"`, while rejecting should resume to `communication_plan="internal_updates_only"`.

```bash
replayt run replayt_examples.e09_incident_response:wf \
  --inputs-json '{"incident":{"service":"api","error_rate":12.5,"customer_impact":"Checkout requests are failing for many customers.","suspected_cause":"Database connection pool exhaustion"}}'
```

For a sev1 incident, approve external comms:

```bash
replayt resume replayt_examples.e09_incident_response:wf <run_id> --approval exec_comms
```

Or keep the response internal-only:

```bash
replayt resume replayt_examples.e09_incident_response:wf <run_id> --approval exec_comms --reject
```

### What to expect

With `error_rate=12.5`, the sample incident is `sev1`. That means the run should:

- store `severity="sev1"`
- log a tool call to `page_on_call`
- log a tool call to `create_statuspage_draft`
- pause on approval `exec_comms`

If approved, the final context should include `communication_plan="external_statuspage_and_internal_slack"`.

If rejected, the final context should include `communication_plan="internal_updates_only"`.

## 10. GitHub issue triage - `replayt_examples.issue_triage`

<p align="center">
  <img src="../../docs/demo.svg" alt="replayt demo: run, inspect, replay on issue triage" width="820"/>
</p>

This example shows how deterministic validation and LLM classification can work together.

### What the code does

The workflow starts with `validate`, which checks that the issue payload exists and flags obviously incomplete title/body fields. It then moves to `classify`:

- if required fields are missing, the workflow avoids an LLM classification and routes to `respond`
- otherwise, the model produces a `TriageDecision`
- if the model says more information is needed, the workflow still routes to `respond`
- if not, the workflow routes to `route`

The `route` step turns that decision into a smaller `routing` object with queue, label, and priority.

### What to run
A developer workflow with deterministic validation, LLM classification, and explicit routing.

With the sample input, the issue should pass validation, the LLM should return a `TriageDecision`, and the final context should either contain a `response_template` asking for clarification or, more likely here, a `routing` object with a category-backed queue, suggested label, and priority for engineering triage.

```bash
replayt run replayt_examples.issue_triage:wf \
  --inputs-json '{"issue":{"title":"Crash on save","body":"Open app, click save, stack trace appears, expected file write."}}'
```

### What to expect

The sample input is long enough to pass validation, so classification is the main step to watch. The final context should contain one of two outcomes:

- `response_template` if the model decides more information is needed
- `routing` if the model is confident enough to classify and route

For this particular issue, a bug-style classification and engineering-oriented routing are the most likely result. Control flow stays explicit even when a model is involved.

## 11. Refund policy workflow - `replayt_examples.refund_policy`

<p align="center">
  <img src="../../docs/demo-debug.svg" alt="replayt debugging a failed refund_policy run" width="820"/>
</p>

This example shows a constrained customer-support decision with structured LLM output.

### What the code does

The workflow:

- validates `ticket` and `order` in `ingest`
- asks the model for a schema-valid `RefundDecision` in `decide`
- copies the relevant fields into `summary_for_agent` in `summarize`

The prompt narrows the policy space: refund, reship, store credit, deny, or escalate.

### What to run
A constrained support decision flow where the output space stays narrow and auditable.

With the sample input, the run should finish successfully and `summary_for_agent` should contain the schema-validated refund action, reason codes, and customer message. For this damaged-order ticket delivered 3 days ago, the policy allows a refund-oriented outcome, but the exact action still comes from the model and stays visible in the log.

```bash
replayt run replayt_examples.refund_policy:wf \
  --inputs-json '{"ticket":"My order arrived damaged and I need a refund.","order":{"order_id":"ORD-1001","amount_cents":12999,"delivered":true,"days_since_delivery":3}}'
```

### What to expect

The model still has discretion, but it must answer inside a bounded schema. After the run, `summary_for_agent` should contain:

- `action`
- `reason_codes`
- `customer_message`

Because the order was delivered only 3 days ago and the ticket reports damage, a refund-oriented action is reasonable under the stated policy. The output stays structured and reviewable instead of buried in prose.

## 12. Publishing preflight with approval gate - `replayt_examples.publishing_preflight`

<p align="center">
  <img src="../../docs/demo-approval.svg" alt="replayt approval gate: pause, review, resume" width="820"/>
</p>

This example combines structured LLM review with a human publication decision.

### What the code does

The `checklist` state asks the model to evaluate a draft against a strict checklist and return a `ChecklistResult` object. The workflow stores that result, builds an `approval_summary`, and then moves into `approval`.

The `approval` state behaves much like the travel example:

- if already approved, continue to `finalize`
- if rejected, continue to `abort`
- otherwise pause and request `publish`

### What to run
Check draft copy, generate a structured checklist, and pause for a human publishing decision.

With the sample input, the draft should produce a checklist with one or more issues about unsupported or risky claims, then pause for `publish` approval; approving should resume to `publish_status="approved"`, while rejecting should resume to `publish_status="aborted"`.

```bash
replayt run replayt_examples.publishing_preflight:wf \
  --inputs-json '{"draft":"We guarantee 200% returns forever.","audience":"general"}'
```

Approve it:

```bash
replayt resume replayt_examples.publishing_preflight:wf <run_id> --approval publish
```

Reject it instead:

```bash
replayt resume replayt_examples.publishing_preflight:wf <run_id> --approval publish --reject
```

### What to expect

The sample draft is risky, so the checklist should likely report `passes=false` and one or more issues related to unsupported claims or inappropriate guarantees. The first run should then pause for `publish` approval.

If approved, the resumed run should end with `publish_status="approved"`.

If rejected, the resumed run should end with `publish_status="aborted"`.

Use this when an LLM prepares structured guidance but a human still makes the final decision.

## Python file target

replayt can load a workflow directly from a Python file if it exports `wf` or `workflow`.

```bash
replayt run workflow.py --inputs-json '{"ticket":"hello"}'
```

## YAML workflow target

For small declarative flows, replayt can run a workflow directly from YAML.

```bash
replayt run workflow.yaml --inputs-json '{"route":"refund","ticket":"where is my order?"}'
```

## Graph export

```bash
replayt graph replayt_examples.e04_tool_using_procurement:wf
```

---

## 13. OpenAI SDK integration - `replayt_examples.e10_openai_sdk_integration`

This example uses the official `openai` Python SDK inside replayt steps: function calling with Pydantic validation, the `tools` parameter, and streaming with a structured summary pass. Transitions and approvals stay in replayt; the SDK lives inside individual step handlers. Requires `pip install openai`.

```bash
replayt run replayt_examples.e10_openai_sdk_integration:wf \
  --inputs-json '{"issue_title":"Login page crashes on mobile","issue_body":"Steps: open login on iOS Safari, tap submit, white screen."}'
```

## 14. Anthropic native SDK - `replayt_examples.e11_anthropic_native`

Use this pattern when you want `anthropic.Anthropic()` directly instead of an OpenAI-compatible proxy. LLM traffic from native SDKs is **not** auto-logged by replayt; validated `ctx.set` outputs are your audit surface. Requires `pip install anthropic`.

```bash
replayt run replayt_examples.e11_anthropic_native:wf \
  --inputs-json '{"text":"The new dashboard is fast and intuitive, but the export feature keeps timing out on large datasets."}'
```


---

**Composition patterns** (approval bridge, batch drivers, async/webhook workarounds, DuckDB, encryption sketches, and more) live in **[docs/EXAMPLES_PATTERNS.md](../../docs/EXAMPLES_PATTERNS.md)** so this file stays a linear tutorial.
