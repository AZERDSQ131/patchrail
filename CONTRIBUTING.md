# Contributing

Thanks for helping improve PatchRail.

The easiest contribution is a sanitized CI failure fixture:

1. Copy the smallest failing log excerpt that still shows the root cause.
2. Remove secrets, private repo names, user names, and internal paths.
3. Add the fixture under `examples/ci-triage/` or `tests/fixtures/`.
4. Add or update a test that checks the expected failure class.
5. Run `pytest`.

## Pull request checklist

- No secrets or raw private logs added.
- No new network access without explicit opt-in.
- No new write action without human approval.
- No bounty claiming or mass-commenting behavior.
- CLI examples still work.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```
