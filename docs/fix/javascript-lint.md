<!-- Canonical: https://getpatchrail.com/fix/javascript-lint -->

# JavaScript and TypeScript lint — eslint no-unused-vars / prettier

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/javascript-lint](https://getpatchrail.com/fix/javascript-lint)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
error  'x' is defined but never used  no-unused-vars
lint failed
Code style issues found in the above file. Run Prettier to fix.
biome check
```

## What actually happened

ESLint, Biome, or Prettier (in check mode) exited non-zero. Same family as Python lint, JS flavor. The signatures worth respecting rather than silencing: no-unused-vars can mask a refactor that disconnected real logic; unused imports of modules with side effects change behavior when "cleaned up." Prettier check failures mean a file wasn't formatted with the project's config — almost always an editor without the plugin or a config version mismatch.

## Fix it

1. Run the project's own lint script locally — it carries the flat-config/legacy-config choice and plugin set that ad-hoc npx eslint . won't.
2. --fix for mechanical rules; review the diff.
3. For rules requiring judgment, fix or disable per-line with a reason (// eslint-disable-next-line rule -- why). Per-file or global disables to pass one PR are how lint configs rot.
4. Prettier conflicts with ESLint formatting rules (endless flip-flopping fixes): the configs overlap — adopt eslint-config-prettier to remove formatting rules from ESLint and let Prettier own formatting.
5. Rerun the exact CI lint command.

## Prevent it

- Same as Python — pre-commit hook (husky/lint-staged) pinned to CI's versions, formatting on save in the team editor config.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=javascript-lint)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
