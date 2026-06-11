<!-- Canonical: https://getpatchrail.com/fix/typescript-typecheck -->

# TypeScript type checking — TS2339 / is not assignable

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/typescript-typecheck](https://getpatchrail.com/fix/typescript-typecheck)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
error TS2339: Property 'x' does not exist on type
error TS2769: No overload matches this call
Type 'string' is not assignable to type 'number'
Object is possibly 'undefined'
error TS2304: Cannot find name
```

## What actually happened

tsc --noEmit (or vue-tsc) found type errors; every error carries a TS____ code. The recurring patterns: TS2339 Property does not exist on type after a dependency bump — the library's types changed shape; TS2769 No overload matches this call — usually one wrong argument, but TypeScript prints every candidate overload, so the error looks enormous (read only the last "argument of type X is not assignable" line of the block); Object is possibly 'null'/'undefined' — strict null checking doing its job; Cannot find name — a missing import or a missing @types/ package, not a logic error.

## Fix it

1. Reproduce with the project's own typecheck script (it encodes the right tsconfig and tool — vue-tsc vs tsc matters).
2. Fix the first error in a file before recompiling judgment on the rest — TypeScript errors cascade hard; one bad import can produce fifty downstream errors.
3. No overload matches: read only the final nested "not assignable" reason. That's the actual mismatch.
4. Null-possibly errors: narrow with real checks (if (!x) return, optional chaining). Each ! non-null assertion is a deferred runtime crash — budget them like debt.
5. Library type drift after upgrade: check the package's release notes/migration guide for the types change before "fixing" your call sites one by one — there's usually one intended new pattern.

## Prevent it

- Run tsc --noEmit in CI even if your bundler (vite/esbuild/swc) skips type checking at build time — bundlers compile type-broken code happily, and without the gate the errors surface in editors, gradually, forever.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=typescript-typecheck)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
