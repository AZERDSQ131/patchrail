<!-- Canonical: https://getpatchrail.com/fix/git-merge-conflict -->

# Merge and rebase conflicts — Automatic merge failed; fix conflicts

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/git-merge-conflict](https://getpatchrail.com/fix/git-merge-conflict)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Automatic merge failed; fix conflicts and then commit the result
CONFLICT (content): Merge conflict in src/app.ts
error: Merging is not possible because you have unmerged files
error: could not apply a1b2c3d
You have unmerged paths
```

## What actually happened

CI tests the merge result of your branch with the base branch (refs/pull/N/merge on GitHub), not your branch tip. When base moved and now conflicts with your branch, that synthetic merge fails before any build step. Your branch may be green in isolation; the merge is what's red. The conflict type in the signature matters: content is a normal overlapping edit; modify/delete means someone deleted a file you modified (the resolution is a decision, not an edit); submodule means two branches pinned different submodule commits.

## Fix it

1. Update and merge locally: git fetch origin && git merge origin/<base> (or rebase, per your team's convention).
2. Resolve each conflicted file: git status lists them under Unmerged paths. For modify/delete, decide explicitly whether the file lives or dies — don't just keep "your" side reflexively.
3. Re-run the affected tests locally before pushing — semantic conflicts (both sides valid alone, broken together) survive textual resolution.
4. Commit the resolution and push; CI re-runs against a fresh merge.
5. If the same files conflict repeatedly across PRs, that's an architecture smell — a hotspot file shared by everyone (a giant routes file, a central constants module). Split it.

## Prevent it

- Merge or rebase onto base early and often on long-lived branches. Conflict pain grows superlinearly with divergence time.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=git-merge-conflict)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
