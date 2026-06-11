<!-- Canonical: https://getpatchrail.com/fix/release-publish-failure -->

# Publish and release conflicts — EPUBLISHCONFLICT / File already exists

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/release-publish-failure](https://getpatchrail.com/fix/release-publish-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
You cannot publish over the previously published versions
EPUBLISHCONFLICT
HTTPError: 400 File already exists
crate version 1.2.3 is already uploaded
a release with the same tag already exists
```

## What actually happened

Two causes cover nearly everything: version-already-exists (EPUBLISHCONFLICT, PyPI's "File already exists", crates.io's "already uploaded", GitHub's "already_exists" on a tag) — most registries are immutable by design; you can never republish a version, even to fix it. This fires when a release job re-runs after a partial failure (half the artifacts published, half didn't) or when the version wasn't bumped. And auth failures (ENEEDAUTH, E403, 403 Forbidden) — the publish credential is missing, expired, or lacks rights to this package name; PyPI in particular returns 403 (not 404) for "name taken by someone else."

## Fix it

1. Determine which artifacts of the release actually made it (check the registry directly). Partial publishes are the norm in this failure class.
2. Version conflict: bump the version — even for a one-character fix. Fighting registry immutability is a losing game, and it exists so that a given version is forever the same bytes for everyone.
3. Re-run only the publish step, with already-published artifacts skipped (twine upload --skip-existing, conditional steps per artifact). Re-running the whole release pipeline re-builds and can produce different bytes.
4. Auth: verify which token the step actually uses (env var name, trusted-publisher config) and its scopes/expiry. Don't print it while debugging.
5. Tag conflicts: decide whether the existing tag is the release (then skip creation) or a stale tag (then delete deliberately, knowing consumers may have fetched it).

## Prevent it

- Make releases idempotent — every publish step either skips-if-exists or is conditional on a registry check. A safely re-runnable release pipeline turns this whole class into a non-event.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=release-publish-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
