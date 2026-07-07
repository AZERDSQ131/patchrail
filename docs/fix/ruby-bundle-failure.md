<!-- Canonical: https://getpatchrail.com/fix/ruby-bundle-failure -->

# Ruby Bundler failures — Bundler could not find compatible versions

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/ruby-bundle-failure](https://getpatchrail.com/fix/ruby-bundle-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Bundler could not find compatible versions for gem
Could not find gem
Gem::Ext::BuildError: ERROR: Failed to build gem native extension
Your bundle is locked to
An error occurred while installing
```

## What actually happened

Three distinct causes: (1) version solving ("Bundler could not find compatible versions") — same logic as pip resolution, read the dependency chain Bundler prints; (2) locked Bundler/gem mismatch ("Your bundle is locked to") — the Gemfile.lock pins a Bundler version or platform different from CI's, common after a Ruby image bump or when a dev on macOS locks without the Linux platform; (3) native extension build failure (Gem::Ext::BuildError, "An error occurred while installing") — gems like nokogiri, pg, mysql2 compile C at install time and need system libraries (libpq-dev, libxml2-dev...) the CI image doesn't have.

## Fix it

1. Find the first failing gem in the log — everything after it is cascade.
2. Gem::Ext::BuildError: scroll up inside the extension build output to the actual compiler error; it names the missing header (libpq-fe.h: No such file or directory → install libpq-dev). Add the system package to the CI image/step.
3. Your bundle is locked to: align the Bundler version (gem install bundler -v <locked>) or update the lock (bundle update --bundler). For platform issues: bundle lock --add-platform x86_64-linux.
4. Version solving: relax the narrowest constraint in the Gemfile, bundle lock, rerun.
5. rake aborted! / RSpec failures after a successful install are a test failure, not a bundle failure — triage as a test failure.

## Prevent it

- Lock platforms explicitly (bundle lock --add-platform x86_64-linux) so macOS-generated lockfiles work on Linux CI, and bake native build deps into the CI image.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
