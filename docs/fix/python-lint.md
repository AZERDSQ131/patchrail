<!-- Canonical: https://getpatchrail.com/fix/python-lint -->

# Python lint and formatting — F401 / would reformat

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/python-lint](https://getpatchrail.com/fix/python-lint)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
F401 imported but unused
E501 line too long (92 > 88 characters)
1 file would be reformatted
Imports are incorrectly sorted
Your code has been rated at
```

## What actually happened

A linter or formatter exited non-zero — the tests may be perfectly green. Identify which tool: ruff/flake8 codes (F401 unused import, E501 line too long), pylint's named messages ((unused-variable)) and its "rated at" summary, black's "would reformat" (running in --check mode: it changed nothing, it's telling you it would), isort's "Imports are incorrectly sorted". One genuinely important nuance: F401 / undefined-variable class findings are correctness-adjacent — an unused import can mask a typo'd import that something else needed; an undefined name is a latent NameError. Don't bulk-silence those.

## Fix it

1. Identify the exact tool and run it locally at CI's version (ruff --version vs the CI log — lint rules change between minor versions).
2. Auto-fix what's mechanical: ruff check --fix, black ., isort .. Review the diff — auto-fixes are safe but not always pretty.
3. For judgment findings (docstrings, complexity), fix or suppress inline with a reason (# noqa: E501  # long URL) — never blanket-disable a rule repo-wide to pass one PR.
4. Touch only files your change touched. A "fix lint" commit that reformats 200 untouched files makes the PR unreviewable.
5. Rerun the same linter command CI uses (copy it from the workflow, not from memory).

## Prevent it

- Run the formatter+linter as a pre-commit hook pinned to the same versions as CI (pre-commit's lockfile does this). Lint failures in CI should be rare events, not a routine round-trip.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=python-lint)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
