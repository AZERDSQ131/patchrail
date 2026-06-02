# AGENTS.md

PatchRail is a local-first maintainer automation toolkit. The core safety rule
is: produce evidence and reviewable suggestions; do not perform write actions
without maintainer approval.

## Setup

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```

## Review guidelines

- Treat possible secret leakage as P0.
- Treat new network access without explicit opt-in as P0.
- Treat repository write actions without dry-run and human approval as P0.
- Treat missing fixtures for classifier changes as P1.
- Treat documentation quickstart drift as P1.
- Check that CLI examples still work.

## Safety rules

- Do not add automatic bounty claiming.
- Do not add mass-commenting workflows.
- Do not submit pull requests to third-party repositories automatically.
- Do not send raw CI logs to external services unless explicitly requested.
- Prefer local-first behavior.

## CI classifier changes

When changing classifier logic:

1. Add or update a fixture.
2. Add expected classification metadata.
3. Run the relevant tests.
4. Include evidence lines in the pull request description.

## Release changes

Do not publish packages, create tags, or push release commits unless a maintainer
explicitly asks. Prepare release pull requests only.
