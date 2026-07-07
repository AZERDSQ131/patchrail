<!-- Canonical: https://getpatchrail.com/fix/secrets-or-permissions-failure -->

# Missing secrets and insufficient permissions — Input required and not supplied

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/secrets-or-permissions-failure](https://getpatchrail.com/fix/secrets-or-permissions-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Error: Input required and not supplied
Resource not accessible by integration
remote: Permission to repo denied to github-actions
refusing to allow a GitHub App to create or update workflow
insufficient permission
```

## What actually happened

A credential is missing, empty, or under-scoped. The three big variants: fork PRs — secrets are deliberately not exposed to workflows triggered from forks; a job that passes on branches and fails on fork PRs with "Input required and not supplied" or an empty secret is this, every time, by design. Default token scoping — modern CI defaults GITHUB_TOKEN to read-only; any step that writes (pushes a commit, comments on a PR, publishes a package) fails with "Resource not accessible by integration" until the job declares the scope. Workflow-file protection — "refusing to allow ... to create or update workflow" means a token without the workflows permission tried to push a change touching .github/workflows/, a security guard, not a bug.

## Fix it

1. Identify the exact missing credential or scope from the error line — it usually names the input or permission.
2. Fork-PR case: don't try to expose the secret (that's the vulnerability the design prevents). Split the workflow: run unprivileged checks on pull_request, privileged steps on pull_request_target or after merge — and never run untrusted PR code inside the privileged half.
3. Missing secret: gh secret list, then set it at the right level (repo / environment / org). Check spelling — NPM_TOKEN vs NPM_AUTH_TOKEN mismatches between workflow and settings are endemic.
4. Under-scoped token: add the narrowest scope to the failing job's permissions: block (e.g. contents: write for pushing, pull-requests: write for commenting). Resist write-all.
5. Rerun only the failing step's job.

## Prevent it

- Declare an explicit least-privilege permissions: block in every workflow. Implicit defaults change over time; explicit blocks fail loudly and document intent.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
