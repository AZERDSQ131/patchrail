<!-- Canonical: https://getpatchrail.com/fix/node-test-failure -->

# Node test runner failures — Tests: N failed / Expected: Received:

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/node-test-failure](https://getpatchrail.com/fix/node-test-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Tests:       2 failed, 18 passed
Test Suites: 1 failed
Expected: 4   Received: 3
FAIL src/app.test.ts
toMatchSnapshot
```

## What actually happened

First, confirm this is a unit runner and not a browser E2E suite — the fix strategies differ completely. Then the signature tells you the flavor: "Expected: ... Received:" is a value assertion (real drift); toMatchSnapshot failures are their own category — the rendered output changed, and the question is whether the change was intentional (update the snapshot) or a regression (fix the code), and snapshot tests can't tell you which; "Test Suites: N failed" with zero individual test failures means suites crashed at import time (syntax error, bad transform config, ESM/CJS mismatch) — config problem, not assertion problem.

## Fix it

1. Rerun only the failing spec: npx jest path/to/file.test.ts -t "test name" or npx vitest run path/to/file.test.ts.
2. Suite-level crash (failed suite, no failed tests): read the import-time error. Usual suspects: transform config (ts-jest/babel vs ESM), a dependency that ships untranspiled ESM, Node version drift.
3. Snapshot failures: review the printed diff as a code review, not as noise. Intentional → jest -u and commit the updated snapshot in the same PR as the change that caused it. Unintentional → it caught a regression; fix the code.
4. Value assertions: standard fix — decide whether code or expectation is wrong, change exactly one.
5. Flaky in CI only: look for unawaited promises and timer dependence — run with --runInBand to rule out worker parallelism, and check for setTimeout-based waits in the test.

## Prevent it

- Ban bare setTimeout waits in tests (use fake timers or condition polling). Timer-based tests are the top source of CI-only flakiness in Node suites.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=node-test-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
