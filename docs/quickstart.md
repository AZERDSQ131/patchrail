# Quickstart

## 10-second reviewer demo

No install is required to inspect the current behavior. The versioned demo at
[examples/ci-triage/demo-output.md](../examples/ci-triage/demo-output.md) is real
CLI output from the bundled `examples/ci-triage/dependency-failure.log` fixture,
and tests compare that file against the command output to prevent drift.
For a single local reviewer smoke test from a source checkout, run:

```bash
uv run --extra dev python scripts/reviewer_quick_check.py
uv run --extra dev patchrail evidence reviewer-packet --out-dir patchrail-reviewer-packet
uv run --extra dev patchrail evidence verify-reviewer-packet patchrail-reviewer-packet --format markdown
```

The reviewer packet verifier recomputes every listed artifact's byte size and
SHA-256 digest, rejects symlinked or non-file artifacts, rejects extra files,
and exits non-zero if the packet has been tampered with or drifted from its
manifest.

PyPI publishing is pending, so `pipx install patchrail` will not work yet. Until
the package is published there, run the public GitHub source directly:

```bash
uvx --from git+https://github.com/patchrail/patchrail patchrail --help
printf 'python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n' \
  | uvx --from git+https://github.com/patchrail/patchrail patchrail ci explain
```

That pre-PyPI smoke test prints:

```markdown
# PatchRail CI Report

- Root cause: `python_test_failure`
- Confidence: `0.89`
- Subsystem: Python tests
- Reproduce: `python -m pytest -q`
- Suggested action: Reproduce the failing test, patch the narrow behavior drift, and rerun the focused pytest node before broad test runs.

## Evidence signals

- `\bpytest\b`
- `FAILED .*::`
- `AssertionError`

## Safety

PatchRail classified this log locally. It did not create a pull request, post a comment, claim funding, or send data to an external service.
```

Or install the v0.1.0 release wheel directly from GitHub Releases:

```bash
python -m pip install https://github.com/patchrail/patchrail/releases/download/v0.1.0/patchrail-0.1.0-py3-none-any.whl
patchrail --help
```

Confirm the local installation and safety boundary:

```bash
patchrail doctor
```

Classify a failed CI log:

```bash
patchrail ci classify --log failed-github-actions.log --format json
```

Render a maintainer-readable report:

```bash
patchrail ci explain --log failed-github-actions.log --format markdown
```

Redact a log before sharing it:

```bash
patchrail redact --log failed-github-actions.log > failed-github-actions.redacted.log
```

Create a local pilot pack for maintainer review:

```bash
patchrail ci pilot-pack --log failed-github-actions.log --out-dir patchrail-pilot-pack
patchrail ci pilot-summary --pack patchrail-pilot-pack --ci-provider "GitHub Actions" --toolchain Python
```

From a source checkout, run the bundled fixture and benchmark:

```bash
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
uv run --extra dev patchrail ci benchmark examples/ci-triage --format markdown
```

The same fixture has a versioned real-output demo that can be regenerated with:

```bash
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
```

PatchRail v0.1 does not create pull requests, comments, funded issue claims, or
remote uploads. The command reads a local log file and writes a local report.
