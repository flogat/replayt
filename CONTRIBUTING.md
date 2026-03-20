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

## Good first issues (ideas)

- Improve CLI `inspect` / `replay` formatting (keep dependencies light).
- Add a `replayt doctor` command that checks env vars and connectivity.
- More unit tests for edge cases in persistence or approvals.
- Documentation clarifications and recipe snippets.
