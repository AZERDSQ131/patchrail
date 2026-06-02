## Summary

What changed and why?

## Type of change

- [ ] CI classifier logic
- [ ] Fixture or benchmark
- [ ] CLI or output format
- [ ] Docs
- [ ] Security or redaction
- [ ] Agent workflow
- [ ] Funded issue discovery

## Safety checklist

- [ ] No secrets or raw private logs added
- [ ] No new network access without explicit opt-in
- [ ] No write action without dry-run and human approval
- [ ] No bounty claiming or mass-commenting behavior

## Tests

Commands run:

```bash
python -m pytest -q
python -m ruff check .
```
