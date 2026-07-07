<!-- Canonical: https://getpatchrail.com/fix/python-dependency-resolution -->

# Python dependency resolution — ResolutionImpossible

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/python-dependency-resolution](https://getpatchrail.com/fix/python-dependency-resolution)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Could not find a version that satisfies the requirement
ResolutionImpossible
The conflict is caused by:
Requires-Python
No matching distribution found
```

## What actually happened

The resolver (pip, poetry, uv) cannot find a set of versions satisfying all constraints simultaneously. The most common real causes, in order: (1) Python version mismatch — Requires-Python in the log means a pinned package version doesn't support the CI Python version (typically after a CI image bump, or a package dropping an old Python); (2) two of your dependencies pin conflicting versions of a shared transitive dependency ("The conflict is caused by:" names them — read that block, it's the whole answer); (3) a yanked release — a version you pinned was withdrawn from PyPI and fresh resolves stop finding it while cached environments still work, which is why it "works on my machine."

## Fix it

1. Read the resolver's explanation block (The conflict is caused by: / ResolutionImpossible chain). Modern resolvers tell you the exact conflicting pair — believe them.
2. Check the Python version first: does the CI Python match what your constraints assume? A silent image bump (3.11 → 3.13) breaks resolution with zero changes on your side.
3. Relax or align the narrowest constraint involved in the conflict. Prefer widening your pin over forcing a transitive version.
4. yanked: pick the nearest non-yanked release; it was usually yanked for a reason.
5. Re-lock (pip-compile, poetry lock, uv lock) and rerun the exact install command from CI, with the same Python version.

## Prevent it

- Pin the Python version explicitly in CI (don't use a floating 3.x), and use a lockfile for applications. Resolution should happen at lock time, on a developer machine, never at deploy time.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
