<!-- Canonical: https://getpatchrail.com/fix/python-type-check -->

# Python type checking — Found N errors / [arg-type]

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/python-type-check](https://getpatchrail.com/fix/python-type-check)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Found 12 errors in 4 files
error: Argument 1 to "f" has incompatible type
error: Incompatible return value type [return-value]
reportOptionalMemberAccess
is not assignable to parameter
```

## What actually happened

mypy (bracketed codes like [arg-type], "Found N errors in M files") or pyright (reportXxx rules, "N errors, N warnings, N informations") found a type inconsistency. The high-frequency real causes: a dependency bump changed type stubs (suddenly 30 errors in code you didn't touch — the types moved, not your code); union-attr / OptionalMemberAccess — accessing an attribute on X | None without narrowing, which is a genuine latent AttributeError about half the time; import-untyped — a new dependency has no stubs, which is a configuration decision, not a code defect.

## Fix it

1. Confirm the type checker failed, not the tests — and which one, at which version. mypy and pyright disagree routinely; fix what CI runs.
2. Mass errors in untouched code after a dependency bump: the stubs changed. Update annotations to the new types, or pin the stubs package alongside the runtime package.
3. Optional-access errors: narrow properly (if x is not None: / early return). Reach for assert x is not None only when invariants truly guarantee it — each one is a runtime crash if you're wrong.
4. import-untyped: add the stubs package (types-<name>) if it exists; otherwise a scoped per-module ignore in config — not # type: ignore scattered through code.
5. Fix the narrowest mismatch and rerun the checker on the affected files first (mypy path/), then fully.

## Prevent it

- Pin the type checker version and stub packages in dev dependencies. Unpinned type checkers turn every mypy/pyright release into a surprise CI failure on someone's unrelated PR.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
