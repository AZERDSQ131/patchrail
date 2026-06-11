<!-- Canonical: https://getpatchrail.com/fix/node-dependency-install -->

# Node package installation — ERESOLVE / npm ci lockfile mismatch

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/node-dependency-install](https://getpatchrail.com/fix/node-dependency-install)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
npm ci can only install packages when your package.json and package-lock.json
ERESOLVE unable to resolve dependency tree
Conflicting peer dependency
404 Not Found - GET https://registry.npmjs.org
ERR_PNPM_NO_MATCHING_VERSION
```

## What actually happened

Three dominant variants: lockfile drift ("npm ci can only install packages when your package.json and package-lock.json...") — someone edited package.json without regenerating the lockfile, or merged two branches that each touched it; peer dependency conflict (ERESOLVE, Conflicting peer dependency) — two packages demand incompatible versions of a shared peer (React being the classic), and npm ≥7 made this a hard error; registry 404 ("404 Not Found - GET https://registry.npmjs.org/...", "is not in this registry") — a private package being fetched from the public registry (missing .npmrc scope config in CI), an unpublished version, or a dependency-confusion-prone name.

## Fix it

1. Lockfile drift: regenerate locally with the same package manager and major version as CI (npm install, commit the lockfile). Mixed npm/pnpm/yarn lockfiles in one repo guarantee this failure — pick one.
2. ERESOLVE: read which two packages disagree. Upgrade the lagging one if an update exists. --legacy-peer-deps is a tourniquet: acceptable to unblock, never a permanent setting in CI.
3. Registry 404 on a scoped private package: the CI job is missing the .npmrc registry mapping or the auth token for your private registry. Fix config, not package.json.
4. Reproduce with the exact CI command — npm ci, not npm install. They behave differently by design.
5. Change the minimum: one constraint, re-lock, rerun.

## Prevent it

- Enforce one package manager via packageManager in package.json + corepack, and always install with the frozen/ci variant in CI (npm ci, pnpm install --frozen-lockfile). Lockfile drift then fails the PR that caused it, not a random later one.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=node-dependency-install)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
