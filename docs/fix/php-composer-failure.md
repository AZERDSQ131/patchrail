<!-- Canonical: https://getpatchrail.com/fix/php-composer-failure -->

# PHP Composer failures — could not be resolved to an installable set

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/php-composer-failure](https://getpatchrail.com/fix/php-composer-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Your requirements could not be resolved to an installable set of packages
Problem 1
requires php >=8.2
lock file is not up to date
Class not found
```

## What actually happened

Composer prints unusually good diagnostics — Problem 1, Problem 2, each with a root-cause chain. The recurring causes: (1) PHP version mismatch ("requires php >=8.2" while CI runs 8.1) — Composer resolves against the running PHP version; (2) lockfile drift ("lock file is not up to date") — composer.json changed without composer update; (3) missing PHP extension — a package requires ext-intl or ext-gd that the CI image lacks; (4) autoload staleness ("Class ... not found" at runtime after a green install) — a new class isn't in the dumped autoloader, or the namespace doesn't match the path per PSR-4.

## Fix it

1. Read Problem 1 only. Later problems are usually the same root cause restated.
2. PHP mismatch: align CI's PHP with composer.json's require.php — or consciously raise the floor. Check composer check-platform-reqs output.
3. Lockfile drift: composer update --lock (metadata only) or a real composer update <package> for the changed dependency. Commit the lock.
4. Missing extension: install it in the CI step (e.g. docker-php-ext-install intl) — don't --ignore-platform-reqs, which converts an install error into a runtime fatal.
5. Class ... not found: composer dump-autoload -o; if it persists, the namespace/path mismatch is real — fix the file location, not the autoloader.

## Prevent it

- Pin the platform in composer.json (config.platform.php) so resolution is identical on every machine regardless of locally installed PHP.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=php-composer-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
