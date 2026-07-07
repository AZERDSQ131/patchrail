<!-- Canonical: https://getpatchrail.com/fix/rust-test-failure -->

# Rust test failures — error[E____] / thread panicked

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/rust-test-failure](https://getpatchrail.com/fix/rust-test-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
error[E0308]: mismatched types
thread 'tests::it_works' panicked
test result: FAILED
assertion `left == right` failed
```

## What actually happened

Two very different failures share this class: error[E____] is a compile error — your tests never ran (Rust error codes are exceptionally well documented; rustc --explain E0308 gives you a worked example). thread '...' panicked + test result: FAILED is a runtime test failure — an assert!/assert_eq! miss, an explicit panic!, or an unwrap() on None/Err inside test or code under test. The thread name in the panic line is the test name — that's your rerun target.

## Fix it

1. Compile errors first: cargo test won't run anything until the crate compiles. Fix the first error[E____]; later errors are often cascade.
2. Runtime failure: rerun just that test with output visible: cargo test test_name -- --nocapture --exact.
3. unwrap() panics in code under test: the fix is usually error propagation (?) at the panicking call, not in the test.
4. Set RUST_BACKTRACE=1 in CI's env permanently — a panic without a backtrace wastes one full round-trip per failure.
5. Rerun the crate's tests (cargo test -p <crate>) before the workspace.

## Prevent it

- Deny unwrap() in production paths via clippy (#![warn(clippy::unwrap_used)]) — most "test failures" of the panic flavor are unwraps that should have been ? all along.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
