<!-- Canonical: https://getpatchrail.com/fix/github-actions-workflow -->

# Broken workflow wiring — Invalid workflow file / Unable to resolve action

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/github-actions-workflow](https://getpatchrail.com/fix/github-actions-workflow)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Invalid workflow file
Unable to resolve action
Resource not accessible by integration
.github/workflows
```

## What actually happened

The pipeline definition itself is broken — the job often fails before a single line of your code runs. "Invalid workflow file" is YAML or schema breakage (bad indentation, an if: expression with a syntax error, a typo'd key). "Unable to resolve action" means a referenced action or version doesn't exist — a typo'd tag, a deleted action, or a private action referenced from a repo that can't see it. "Resource not accessible by integration" is the workflow's token lacking a permission its steps need (this overlaps with the secrets/permissions class — if you see it next to secrets language, read that entry too).

## Fix it

1. Confirm the failure happens at workflow-parse time or in the first setup steps, not in your build.
2. Validate the YAML: gh workflow view <name> --yaml, or actionlint locally — it catches schema errors, bad action refs, and invalid expressions in seconds.
3. For Unable to resolve action: check the uses: line character by character. Verify the tag exists on the action's repo. For private actions, verify repo visibility/access.
4. For Resource not accessible by integration: add the narrowest missing scope to the permissions: block of the failing job, not the whole workflow.
5. Change only the broken job or stanza. Workflow files attract drive-by refactors that break other jobs.

## Prevent it

- Run actionlint as a pre-commit hook or an early CI step. Workflow syntax errors should never reach a push.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=github-actions-workflow)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
