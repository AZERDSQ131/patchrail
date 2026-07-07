<!-- Canonical: https://getpatchrail.com/fix/terraform-iac-failure -->

# Terraform and IaC failures — Error acquiring the state lock

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/terraform-iac-failure](https://getpatchrail.com/fix/terraform-iac-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Error acquiring the state lock
Error: Inconsistent dependency lock file
Error: Failed to install provider
Error: Reference to undeclared resource
Error: Unsupported argument
```

## What actually happened

Stage determines cause: init-stage failures (Inconsistent dependency lock file, Failed to install provider, Module not installed) are environment/lockfile problems — the .terraform.lock.hcl doesn't match required providers, or lacks hashes for CI's platform (locked on macOS, running on Linux). Plan-stage HCL errors (Reference to undeclared resource, Unsupported argument, Invalid value for) are real configuration defects — Unsupported argument after a provider upgrade means the provider's schema changed under you. "Error acquiring the state lock" is operational: another run holds the lock, or a previous run crashed while holding it and the lock is stale. And apply-stage failures after a good plan ("planned the following actions, but then encountered a problem") are the dangerous ones — the cloud API rejected something at execution time, possibly mid-apply, leaving partial state.

## Fix it

1. Identify the stage (init / validate / plan / apply) from the command in the log; it routes everything.
2. Lock file: regenerate with all CI platforms — terraform providers lock -platform=linux_amd64 -platform=darwin_arm64 — and commit. Never delete the lockfile to "fix" it; that's how provider versions drift silently.
3. State lock: find whether a run is genuinely in progress. Only when you've confirmed the holder is dead: terraform force-unlock <lock-id> (the ID is in the error). Force-unlocking a live run corrupts state.
4. HCL errors: fix the named resource/argument. After provider upgrades, read the provider changelog before mass-editing — there's usually a documented migration.
5. Failed applies: run terraform plan again immediately and read it as a damage report — it shows what got created before the failure and what's still pending. Reconcile before any new changes.

## Prevent it

- Pin provider versions with ~> constraints, commit the lock file with all platforms, and upgrade providers in dedicated PRs where the plan diff gets real review.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
