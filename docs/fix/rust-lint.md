<!-- Canonical: https://getpatchrail.com/fix/rust-lint -->

# Rust lint (clippy) — error[clippy::...] / -D warnings

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/rust-lint](https://getpatchrail.com/fix/rust-lint)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
error: this `if` has identical blocks
warning: clippy::needless_return
could not compile due to clippy errors
note: `-D warnings` implied by `-D clippy::all`
```

## What actually happened

Clippy found lints and the build runs with -D warnings, promoting every warning to a hard error. The structural cause of surprise clippy failures: a Rust toolchain update shipped new lints. Your code didn't change; the linter got stricter. Clippy lints come in tiers (correctness/suspicious lints are near-always real bugs; style/pedantic lints are judgment) — the tier should drive how seriously you take the finding.

## Fix it

1. Reproduce with the exact CI invocation, including --all-targets (lints in tests/benches don't show without it) and the same toolchain (rustc --version vs CI).
2. cargo clippy --fix handles the mechanical cases; review the diff.
3. Correctness-tier lints: treat as bug reports, fix properly.
4. Style lints you disagree with: #[allow(clippy::lint_name)] at the narrowest scope with a comment — or set project policy in Cargo.toml's [lints] table so the decision is made once, visibly.
5. After a toolchain bump triggers a lint wave: fix in a dedicated PR, separate from feature work.

## Prevent it

- Pin the toolchain via rust-toolchain.toml and upgrade it deliberately in its own PR — that converts "CI broke overnight" into "we upgrade Tuesday and fix new lints then."

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=rust-lint)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
