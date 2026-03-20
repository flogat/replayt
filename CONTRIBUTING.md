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

**Prerequisites (one-time repo setup):**
- A `pypi` environment must exist in the GitHub repo (Settings > Environments).
- The repo must be registered as a trusted publisher on [pypi.org](https://pypi.org/manage/account/publishing/).

## Good first issues (ideas)

- Improve CLI `inspect` / `replay` / `report` formatting (keep dependencies light).
- Add or refresh an [asciinema](https://asciinema.org/) (or short screen recording) linked from the README.
- More unit tests for edge cases in persistence or approvals.
- Documentation clarifications, [`docs/QUICKSTART.md`](docs/QUICKSTART.md) tweaks, and recipe snippets.
