# Contributing

## Dev setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m build
pytest
ruff check src tests
```

You can invoke the CLI as **`python -m replayt`** (same as the **`replayt`** script) when verifying editable installs or when **`Scripts/`** is not on **`PATH`**.

The `dev` extra includes the YAML dependency and package build tooling so local checks match CI.

## Scope

replayt keeps a narrow core scope. PRs that push it toward a general agent platform probably will not land.

## Versioning (semver)

- **MAJOR:** breaking Python API, CLI behavior users rely on, or **documented** JSONL event payload shapes that consumers parse.
- **MINOR:** backward-compatible additions such as new optional CLI flags, new optional `Workflow` / `Runner` kwargs like `Workflow(..., llm_defaults=...)`, new optional event fields, new optional fields on stable JSON reports such as **`replayt.version_report.v1`**, or new names in `replayt.__all__`. When you bump **`__version__`**, keep **`__version_tuple__`** in lockstep: it is the leading **`X.Y.Z`** numeric prefix of the string.
- **PATCH:** bug fixes and docs that do not change runtime contracts.

Tutorial imports under `replayt_examples` should keep working across **minor** releases when pinned to a compatible **major**.

**Pull requests:** CI runs `scripts/check_changelog_if_needed.py` on PRs. If you touch `src/replayt/`, `src/replayt_examples/`, or `docs/RUN_LOG_SCHEMA.md`, update **`CHANGELOG.md`** in the same PR (add a bullet under **Unreleased** or the next version).

## Releasing a new version

Publishing to PyPI is automated via GitHub Actions. To cut a release:

1. Bump the version in **both** `pyproject.toml` and `src/replayt/__init__.py`.
2. Commit the bump (e.g. `git commit -am "bump version to X.Y.Z"`).
3. Tag the commit and push:
   ```bash
   git tag vX.Y.Z
   git push origin main --tags
   ```
4. The `publish` workflow runs tests across Python 3.10 to 3.12, builds the package, and uploads it to PyPI using trusted publishing (OIDC). No API tokens needed.

The workflow lives in `.github/workflows/publish.yml` and triggers on any tag matching `v*`.

## Maintainer helpers

During release prep or API review, these repo-local scripts keep the public surface and docs inventory explicit:

```bash
python scripts/maintainer_checks.py
python scripts/maintainer_checks.py --format json --changelog-nonempty
python scripts/public_api_report.py --format json
python scripts/public_api_report.py --check docs/PUBLIC_API_CONTRACT.json
python scripts/example_catalog_contract.py --check docs/EXAMPLE_CATALOG_CONTRACT.json
python scripts/check_docs_index.py
python scripts/changelog_unreleased.py --check-nonempty
python scripts/changelog_gate_policy.py --format json
python scripts/version_consistency.py
python scripts/pyproject_pep621_report.py --format json
```

- `maintainer_checks.py` runs the version, Unreleased changelog, docs index, packaged-example catalog snapshot, and checked-in public API contract checks above in one process, plus a parse of **`pyproject.toml`** **`[project]`** PEP 621 metadata and a machine-readable **PR changelog gate** policy snapshot (optional `--changelog-nonempty`, `--skip-*` for partial trees, `--verbose` JSON with embedded sub-reports).
- `public_api_report.py` snapshots the top-level `replayt` exports from `__all__`, including any declared-but-missing names that would make semver review or docs examples misleading. Use `--check docs/PUBLIC_API_CONTRACT.json` in CI or before a release, and `--snapshot-out docs/PUBLIC_API_CONTRACT.json` only when you intentionally change the public surface.
- `example_catalog_contract.py` snapshots the packaged `replayt try` tutorial catalog (`replayt_examples.list_packaged_examples()`), so maintainers can diff keys, targets, descriptions, and default inputs against the checked-in `docs/EXAMPLE_CATALOG_CONTRACT.json` contract before shipping a release.
- `check_docs_index.py` verifies that `docs/README.md` still indexes every top-level docs file and that the main README documentation links resolve.
- `changelog_unreleased.py` extracts `CHANGELOG.md` -> `## Unreleased` as text or JSON so release-note work does not depend on ad hoc markdown parsing. JSON output includes **`body_sha256`** (SHA-256 hex of the UTF-8 Unreleased body) for cache keys and drift checks in fork CI, plus **`item_sha256s`** (one digest per top-level bullet, same order as **`items`**) when you need to assert a specific entry changed without comparing full markdown.
- `changelog_gate_policy.py` emits **`replayt.changelog_gate_policy.v1`** JSON listing **`exact_paths`** and **`path_prefixes`** that **`scripts/check_changelog_if_needed.py`** treats as protected on GitHub pull requests, so forks can diff or extend the same rules in CI without copying strings.
- `version_consistency.py` fails fast when `pyproject.toml` `[project].version` and `src/replayt/__init__.py` `__version__` disagree, which catches the common partial-bump footgun before a tag push.
- `pyproject_pep621_report.py` emits **`replayt.pyproject_pep621_report.v1`** JSON with sorted **`dependencies`** and **`optional-dependencies`** groups so forks can diff declared pins against upstream without hand-editing TOML in CI (Python 3.10 uses the optional **`tomli`** dev dependency; 3.11+ uses **`tomllib`**).
- `replayt version --format json` includes **`maintainer_script_schemas`**, listing the stable **`schema`** ids for those script JSON payloads (plus skill-loop **`replayt.skill_invocation.v1`** sidecars) so fork CI can compare `python scripts/changelog_unreleased.py --format json` (and the other helpers) against the installed wheel without opening `scripts/*.py`. The same report includes **`skill_loop_env_contract`** (`replayt.skill_loop_env_contract.v1`) with human-readable descriptions for each injected **`SKILL_*`** / **`REPO_ROOT`** name so wrappers can assert env coverage without scraping this file, plus **`skill_loop_placeholder_contract`** (`replayt.skill_loop_placeholder_contract.v1`) for **`--skill-command`** and **`--check`** template keys (including **`{task}`** vs outer **`task_sha256`**).

### Automated skill-loop release

If you want the repo's Cursor skills to drive a patch release, use `scripts/skill_release_loop.py`.

- Default skill order is `DEFAULT_SKILLS` in `scripts/skill_release_loop.py`: twelve `feat_*` archetype skills (`feat_staff_engineer` through `feat_agent_harness_engineer`), then `review_design_fidelity`, `improvedoc`, `deslopdoc`, `reviewcodebase`. Invoke `/createfeatures` separately when you want a single twelve-archetype brainstorm without running the full loop.
- Skill definitions live under `.cursor/skills/`. The loop uses `--skill-root .cursor/skills` by default and now exposes that resolved directory to backends as both `{skill_root}` and `SKILL_ROOT`. `scripts/run_codex_skill.py` keeps repo-local `.cursor/skills` as the canonical default, honors an explicit `--skill-root`, and only falls back to ambient `SKILL_ROOT` when the repo has no local skill directory. If you use standalone Codex with global skills, copy or symlink those folders into `$CODEX_HOME/skills`.
- With the repo-local Codex install under `.replayt/tools/codex-cli`, `python scripts/skill_release_loop.py` uses the default task plus `scripts/run_codex_skill.py` automatically.
- The script repeats that full cycle until every `--check` command passes or `--max-iterations` is hit.
- `CHANGELOG.md` must be edited during the loop; once checks pass, the script rolls `## Unreleased` into the new version, bumps the patch version in `pyproject.toml` and `src/replayt/__init__.py`, creates an annotated `vX.Y.Z` tag, and pushes the branch plus tag.
- This repo stores the skill prompts only. Pass `--skill-command` with the command that can execute one prompt file.

Example:

```bash
python scripts/skill_release_loop.py \
  --task "Tighten the repo, keep docs honest, and cut the next patch release." \
  --skill-command "python tools/run_skill_backend.py --prompt {prompt_file_q}" \
  --check "python -m build" \
  --check "ruff check src tests scripts" \
  --check "pytest"
```

Available placeholders for `--skill-command`: `{skill}`, `{skill_path}`, `{skill_root}`, `{prompt_file}`, `{log_file}`, `{run_dir}`, `{repo}`, `{iteration}`, `{max_iterations}`, `{task}`, `{step_index}`, `{step_total}`, `{pipeline_sha256}`, `{skill_command_sha256}`, `{task_sha256}` and quoted `*_q` variants such as `{prompt_file_q}`. For normal skills `{task}` is the full shared `--task` string; fix rounds use a short instruction while `{task_sha256}` / `SKILL_TASK_SHA256` stay tied to the outer `--task`. The same values are also exported as environment variables (`SKILL_NAME`, `SKILL_ROOT`, `SKILL_PROMPT_FILE`, `SKILL_PROMPT_REL`, `SKILL_LOG_FILE`, `SKILL_LOG_REL`, `SKILL_RUN_DIR`, `SKILL_RUN_DIR_REL`, `SKILL_STEP_INDEX`, `SKILL_STEP_TOTAL`, `SKILL_PIPELINE_SHA256`, `SKILL_COMMAND_SHA256`, `SKILL_TASK_SHA256`, `REPO_ROOT`, and so on). Within one iteration, `{step_index}` / `{step_total}` count the configured skill sequence (fix prompts use `0` / `0`); `{iteration}` / `{max_iterations}` are the outer release-loop retries. **`replayt version --format json`** includes **`skill_loop_placeholder_contract`** (`replayt.skill_loop_placeholder_contract.v1`) listing every template key with a short description so harnesses avoid scraping this file.

Each run directory also gets a sidecar **`*.invocation.json`** next to every **`*.prompt.md`** (stable schema id **`replayt.skill_invocation.v1`**) with the resolved paths, repo-relative **`prompt_file_rel`** / **`log_file_rel`** / **`run_dir_rel`**, **`skill_command_sha256`** (UTF-8 SHA-256 of the raw **`--skill-command`** template, same as **`SKILL_COMMAND_SHA256`** in the environment), **`task_sha256`** (UTF-8 SHA-256 of the outer loop **`--task`** string, same as **`SKILL_TASK_SHA256`**; fix prompts still carry this digest even when the sidecar **`task`** field is the short fix instruction), sorted **`injected_env_keys`** (names the loop sets alongside optional `GIT_CONFIG_*` for git safe.directory), **`run_dir`**, **`pipeline_sha256`** (same as **`SKILL_PIPELINE_SHA256`** / ordered **`--skills`** fingerprint), **`step_index`** / **`step_total`** (1-based position in the skill list for normal skills; `0` / `0` for fix prompts), iteration metadata, and task text so harnesses can read a JSON contract instead of parsing the Markdown prompt. The first skill phase also writes **`pipeline.json`** once (**`replayt.skill_release_pipeline.v1`**: ordered skill names, pipeline fingerprint, **`skill_command_sha256`**, **`task_sha256`**, and loop task); **`--resume`** fails fast if **`--skills`** order changes versus that file, if **`skill_command_sha256`** no longer matches, or if **`task_sha256`** disagrees with the current **`--task`** (runs whose **`pipeline.json`** predates **`task_sha256`** or **`skill_command_sha256`** skip only the missing digest checks).

To build one JSON array of every invocation under a finished run directory (for dashboards or CI artifacts), keep the atomic per-prompt sidecars and merge them in your layer, for example:

```bash
jq -s '.' .replayt/skill-release/20260322-120000/*.invocation.json
```

For command-heavy docs, prefer ASCII punctuation where practical (`"`, `'`, `...`, `->`) so examples stay readable in stock Windows terminals. See [`docs/STYLE.md`](docs/STYLE.md).

**Prerequisites (one-time repo setup):**
- A `pypi` environment must exist in the GitHub repo (Settings > Environments).
- The repo must be registered as a trusted publisher on [pypi.org](https://pypi.org/manage/account/publishing/).

## Good first issues

- Improve CLI `inspect` / `replay` / `report` formatting (keep dependencies light).
- Refresh [`docs/replayt-demo.cast`](docs/replayt-demo.cast) or add a published asciinema link in [`docs/DEMO.md`](docs/DEMO.md) / the README.
- More unit tests for edge cases in persistence or approvals.
- Documentation clarifications, [`docs/QUICKSTART.md`](docs/QUICKSTART.md) tweaks, and recipe snippets.
