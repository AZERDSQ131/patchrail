<!-- Canonical: https://getpatchrail.com/fix/code-coverage-threshold -->

# Coverage threshold failures — Required test coverage of N% not met

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/code-coverage-threshold](https://getpatchrail.com/fix/code-coverage-threshold)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Required test coverage of 80% not reached
fail_under
Coverage for project (74%) does not meet
is below the expected minimum coverage
SimpleCov failed
```

## What actually happened

All tests passed. The build failed because the coverage percentage fell under a configured threshold (fail_under, jest's coverageThreshold, SimpleCov's minimum, a coverage bot's project target). Mechanically this happens in two ways that feel unfair: you added well-tested code but it shifted file-level percentages, or — more often — you added a small amount of untested code to a small file, where one uncovered branch moves the percentage points. Occasionally the threshold breaks with no code change: a test that silently stopped running (collection error, renamed file not matching the test glob) lowers coverage too — check the test count against the last green run.

## Fix it

1. Confirm tests are green and only the threshold tripped. Compare total test count with the previous green build — a drop means tests went missing, which is the real bug.
2. Get the uncovered lines, not just the percentage: pytest --cov --cov-report=term-missing or open the HTML report. The gate's summary names files; the report names lines.
3. Write focused tests for the uncovered branches your PR introduced. Error paths are usually what's uncovered — and error paths are exactly where untested code hurts.
4. Code that genuinely shouldn't count (debug helpers, platform-specific branches): exclude explicitly (# pragma: no cover with a reason, or config-level exclusions) — visible and reviewable.
5. Lower the threshold only as a deliberate, stated decision in its own commit — never silently inside a feature PR.

## Prevent it

- Gate on patch/diff coverage (new lines covered) rather than absolute project percentage where your tooling allows it — it measures what the PR author actually controls and ends the ratchet fights.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=code-coverage-threshold)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
