<!-- Canonical: https://getpatchrail.com/fix/git-checkout-failure -->

# Checkout, clone, submodule, and LFS failures — Authentication failed

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/git-checkout-failure](https://getpatchrail.com/fix/git-checkout-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
fatal: Authentication failed
fatal: repository not found
fatal: reference is not a tree
Failed to clone submodule
smudge filter lfs failed
```

## What actually happened

Four distinct failures share this class: auth (could not read Username, Authentication failed, Repository not found — which is what private repos return to unauthorized callers, deliberately indistinguishable from "doesn't exist") — the checkout token can't see the repo, classic with private submodules; missing ref (reference is not a tree, pathspec did not match) — the commit you're trying to check out doesn't exist anymore, from a force-push during a run, or a shallow clone (fetch-depth: 1) that doesn't contain the ref a tool needs; submodule drift (Failed to clone/fetch submodule) — the parent repo pins a submodule commit that was rebased away, or the URL moved; LFS (smudge filter lfs failed, error downloading object) — a pointer file references an object the LFS store doesn't have, or LFS bandwidth quota ran out.

## Fix it

1. Classify into one of the four above from the first error line.
2. Auth: confirm what token the checkout uses and what it can see. For private submodules pass an explicit token to the checkout step (with: token: / submodules: recursive).
3. Missing ref: was the branch force-pushed mid-run? Re-trigger on the new head. If a tool needs history or tags, set fetch-depth: 0.
4. Submodule drift: in the parent repo, git submodule update --remote, commit the new pin, push.
5. LFS: git lfs fetch --all locally to find the missing object; check the LFS bandwidth quota before assuming corruption.

## Prevent it

- If you don't strictly need submodules, replace them with package dependencies or vendoring — submodules are the single most failure-prone link between repos. If you keep them, document the token each CI consumer needs.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
