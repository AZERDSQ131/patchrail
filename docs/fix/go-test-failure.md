<!-- Canonical: https://getpatchrail.com/fix/go-test-failure -->

# Go test failures — FAIL / panic: test timed out

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/go-test-failure](https://getpatchrail.com/fix/go-test-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
--- FAIL: TestName
FAIL	github.com/you/pkg	0.42s
undefined: SomeIdentifier
panic: test timed out after 10m0s
```

## What actually happened

Go's signatures are terse and precise. FAIL\t (FAIL + tab) is the per-package failure line — FAIL  github.com/you/pkg  0.42s. "undefined:" is a compile error inside test scope: tests failed to build, often because a test file references an identifier renamed in the main code, or a build tag excluded the file that defines it — nothing actually ran. "panic: test timed out" is Go's 10-minute default test binary timeout: either a genuine deadlock (the panic includes a full goroutine dump — read it, the stuck goroutine is in there) or a suite that legitimately outgrew the limit.

## Fix it

1. Rerun only the failing package and test: go test ./pkg/... -run 'TestName' -v.
2. undefined:: treat as a compile fix. Check build tags (//go:build) if the identifier clearly exists — the file defining it may be excluded for this OS/arch.
3. panic: test timed out: read the goroutine dump at the bottom of the log. Goroutines blocked on a channel/mutex for the full duration name the deadlock. If it's genuinely slow, raise -timeout consciously.
4. Race-flavored flakiness: rerun with -race -count=10. A test that fails intermittently under -count=10 has a real concurrency bug, not "CI weirdness."
5. Fix the narrowest site and rerun the package before ./....

## Prevent it

- Run go test -race in CI always. The race detector converts intermittent heisenbugs into deterministic failures with stack traces.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=go-test-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
