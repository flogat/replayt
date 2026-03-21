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

The `dev` extra includes the YAML dependency and package build tooling so local checks match CI more closely.

## Scope

replayt intentionally stays small. PRs that expand it into a general agent platform are likely to be declined.

## Versioning (semver)

- **MAJOR** — breaking Python API, CLI behavior users rely on, or **documented** JSONL event payload shapes that consumers parse.
- **MINOR** — backward-compatible additions (new optional CLI flags, new optional `Workflow` / `Runner` kwargs such as `Workflow(..., llm_defaults=...)`, new optional event fields).
- **PATCH** — bug fixes and docs that do not change runtime contracts.

Tutorial imports under `replayt_examples` should keep working across **minor** releases when pinned to a compatible **major**.

**Pull requests:** CI runs `scripts/check_changelog_if_needed.py` on PRs. If you touch `src/replayt/`, `src/replayt_examples/`, or `docs/RUN_LOG_SCHEMA.md`, update **`CHANGELOG.md`** in the same PR (add a bullet under **Unreleased** or the next version).

## Releasing a new version

Publishing to PyPI is fully automated via GitHub Actions. To cut a release:

1. Bump the version in **both** `pyproject.toml` and `src/replayt/__init__.py`.
2. Commit the bump (e.g. `git commit -am "bump version to X.Y.Z"`).
3. Tag the commit and push:
   ```bash
   git tag vX.Y.Z
   git push origin main --tags
   ```
4. The `publish` workflow runs tests across Python 3.10–3.12, builds the package, and uploads it to PyPI using trusted publishing (OIDC). No API tokens needed.

The workflow lives in `.github/workflows/publish.yml` and triggers on any tag matching `v*`.

### Automated skill-loop release

If you want the repo's Cursor skills to drive a patch release, use `scripts/skill_release_loop.py`.

- Default skill order: `createfeatures`, `improvedoc`, `deslopdoc`, `reviewcodebase`.
- With the repo-local Codex install present under `.replayt/tools/codex-cli`, `python scripts/skill_release_loop.py` uses the default task plus `scripts/run_codex_skill.py` automatically, so no extra flags are required for the common path.
- The script repeats that full cycle until every `--check` command passes or `--max-iterations` is hit.
- `CHANGELOG.md` must be edited during the loop; once checks pass, the script rolls `## Unreleased` into the new version, bumps the patch version in `pyproject.toml` and `src/replayt/__init__.py`, creates an annotated `vX.Y.Z` tag, and pushes the branch plus tag.
- The repo only stores the skill prompts. You still need to provide a backend command via `--skill-command` that knows how to execute one prompt file.

Example:

```bash
python scripts/skill_release_loop.py \
  --task "Tighten the repo, keep docs honest, and cut the next patch release." \
  --skill-command "python tools/run_skill_backend.py --prompt {prompt_file_q}" \
  --check "python -m build" \
  --check "ruff check src tests scripts" \
  --check "pytest"
```

Available placeholders for `--skill-command`: `{skill}`, `{skill_path}`, `{prompt_file}`, `{log_file}`, `{repo}`, `{iteration}`, `{max_iterations}` and quoted `*_q` variants such as `{prompt_file_q}`. The same values are also exported as environment variables (`SKILL_NAME`, `SKILL_PROMPT_FILE`, `REPO_ROOT`, and so on).

**Prerequisites (one-time repo setup):**
- A `pypi` environment must exist in the GitHub repo (Settings > Environments).
- The repo must be registered as a trusted publisher on [pypi.org](https://pypi.org/manage/account/publishing/).

## Good first issues (ideas)

- Improve CLI `inspect` / `replay` / `report` formatting (keep dependencies light).
- Refresh [`docs/replayt-demo.cast`](docs/replayt-demo.cast) or add a published asciinema link in [`docs/DEMO.md`](docs/DEMO.md) / the README.
- More unit tests for edge cases in persistence or approvals.
- Documentation clarifications, [`docs/QUICKSTART.md`](docs/QUICKSTART.md) tweaks, and recipe snippets.
