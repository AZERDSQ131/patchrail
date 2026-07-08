# pre-commit example for fixture contributors

Contributors adding fixtures under `examples/ci-triage/` have to remember to
run `patchrail ci fixture-check` and `patchrail redact` by hand before
committing (see `CONTRIBUTING.md`). A [pre-commit](https://pre-commit.com)
hook can catch a forgotten secret or a malformed fixture before it ever
reaches a pull request.

This is an example, not a new repo-wide requirement — the manual path in
`CONTRIBUTING.md` still works and is not being replaced.

## Config

Add a `.pre-commit-config.yaml` at the repository root:

```yaml
repos:
  - repo: local
    hooks:
      - id: patchrail-fixture-check
        name: patchrail fixture-check
        entry: bash -c 'uv run --extra dev patchrail ci fixture-check examples/ci-triage --format json'
        language: system
        files: ^examples/ci-triage/
        pass_filenames: false

      - id: patchrail-redact-check
        name: patchrail redact (check for un-redacted secrets)
        entry: >-
          bash -c 'for f in "$@"; do
            diff -q "$f" <(uv run --extra dev patchrail redact --log "$f") ||
              { echo "un-redacted content in $f"; exit 1; };
          done' --
        language: system
        files: ^examples/ci-triage/.*\.log$
```

- `patchrail-fixture-check` runs `patchrail ci fixture-check` whenever any
  file under `examples/ci-triage/` changes, so a malformed or drifted
  fixture is caught locally instead of in CI.
- `patchrail-redact-check` runs `patchrail redact` on each staged `.log` file
  under `examples/ci-triage/` and diffs the result against the file as
  committed. If they differ, something redactable (a token, an email, a home
  path — see `docs/redaction.md`) is still in the fixture, and the hook
  fails with the offending file name.

## Installing and running it

```bash
pipx install pre-commit  # or: uv tool install pre-commit
pre-commit install
```

Run it against everything already in the repo:

```bash
pre-commit run --all-files
```

Or let it run automatically on the files you're committing:

```bash
git add examples/ci-triage/<short-name>.log examples/ci-triage/<short-name>.expected.json
git commit -m "Add fixture: <short-name>"
```

Both hooks are declared with `language: system`, so they call the `uv` and
`patchrail` already on your `PATH` — no separate virtualenv for pre-commit to
manage.

## What this catches

Tested against this repository's fixtures: a `.log` file containing a fake
token (e.g. `ghp_...`) fails `patchrail-redact-check` with an
"un-redacted content" message naming the file; the existing, already-clean
fixtures under `examples/ci-triage/` pass. `patchrail-fixture-check` reports
the same pass/fail counts as running the command directly.
