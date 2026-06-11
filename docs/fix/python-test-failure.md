<!-- Canonical: https://getpatchrail.com/fix/python-test-failure -->

# Python test failures — FAILED test.py::test / AssertionError

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/python-test-failure](https://getpatchrail.com/fix/python-test-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
FAILED tests/test_x.py::test_name
AssertionError
ModuleNotFoundError
E   assert 3 == 4
```

## What actually happened

"FAILED path/to/test.py::test_name" is pytest's failure line — the :: makes it grep-able and gives you the exact node to rerun. The crucial split is AssertionError vs ModuleNotFoundError: an assertion means behavior drifted (a real test failure); ModuleNotFoundError means the test environment is broken — a missing dependency, a packaging/layout problem (src/ layout without installing the package), or a test importing something that was renamed. A wall of failures that are all ModuleNotFoundError for the same module is one environment bug, not N test bugs.

## Fix it

1. Copy the first FAILED node and rerun exactly that: python -m pytest "tests/test_x.py::test_name" -x -q. Seconds, not minutes.
2. ModuleNotFoundError: fix the environment — is the package installed (pip install -e .)? Is the dependency in the right extras group that CI installs? Don't touch test logic.
3. AssertionError: read pytest's diff (it prints both sides). Decide which side is right: the code regressed, or the test encodes outdated expectations. Fix exactly one of them.
4. Passes locally, fails in CI: compare Python versions, then look for test ordering/state leakage — run the failing test alone, then the full suite with -p no:randomly (or with a fixed seed) to confirm an inter-test dependency.
5. Rerun the focused node, then the file, then the suite. Escalate scope only on green.

## Prevent it

- Run tests against the installed package (src layout + pip install -e .) so CI and local imports resolve identically.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=python-test-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
