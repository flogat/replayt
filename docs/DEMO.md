# Demo checklist (launch)

## One-liner smoke

```bash
pip install -e ".[dev]"
replayt graph examples.issue_triage:wf
```

## Record a 60–90s terminal demo

- Tool: [asciinema](https://asciinema.org/) or a screen recorder.
- Suggested flow:
  1. Show `replayt run examples.issue_triage:wf --inputs-json '...'` with `OPENAI_API_KEY` set.
  2. `replayt inspect <run_id>` then `replayt replay <run_id>`.
  3. For approvals: run publishing example, pause, `replayt resume ... --approval publish`, `replayt replay`.

## PyPI publish (manual)

1. Bump version in `pyproject.toml` and `src/replayt/__init__.py`.
2. `python -m build && python -m twine upload dist/*`
3. Tag release in Git.
