# PatchRail

PatchRail is a local-first maintainer automation toolkit for open-source projects.
The first public release focuses on CI failure triage: it reads failed CI logs,
classifies the likely root cause, extracts evidence signals, and emits Markdown,
JSON, or plain text reports that maintainers can review.

PatchRail does not auto-submit pull requests, claim funded issues, or comment on
third-party repositories. It produces evidence and reviewable suggestions so
maintainers stay in control.

## Companion guide

**CI Failure Triage Patterns** — a field guide covering 31 CI failure classes
with the signals that distinguish them and the narrow fix for each. It pairs
directly with the `patchrail ci explain` classifier in this repo:
[patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage).

Read the per-class fixes here: **[docs/fix/](docs/fix/README.md)** — each page lists
the literal log signatures, what actually happened, and the step-by-step fix.

## Quickstart

### 10-second reviewer demo

![patchrail ci explain reading a failed CI log and emitting root cause, confidence, reproduce command, and a fix Guide URL](docs/assets/ci-explain-demo.gif)

`patchrail ci explain` reads a failed CI log and prints the root cause, a
confidence score, a one-line reproduce command, and a `Guide:` link to the
matching fix page. The screenshot above is real output from the bundled
`examples/ci-triage/typescript-import-type-drift.log` fixture.

No install is required to inspect the current behavior. The versioned demo at
[examples/ci-triage/demo-output.md](examples/ci-triage/demo-output.md) is real
CLI output from the bundled `examples/ci-triage/dependency-failure.log` fixture,
and tests compare that file against the command output to prevent drift.
For a single local reviewer smoke test from a source checkout, run:

```bash
uv run --extra dev python scripts/reviewer_quick_check.py
uv run --extra dev patchrail evidence reviewer-packet --out-dir patchrail-reviewer-packet
uv run --extra dev patchrail evidence verify-reviewer-packet patchrail-reviewer-packet --format markdown
uv run --extra dev patchrail evidence control-plane-demo --out-dir .patchrail-demo --force --format markdown
```

The reviewer packet verifier recomputes every listed artifact's byte size and
SHA-256 digest, rejects symlinked or non-file artifacts, rejects extra files,
and exits non-zero if the packet has been tampered with or drifted from its
manifest.

The Control Plane demo command generates a local SQLite queue from the bundled
CI fixture, records approval and rejection gates, writes the reviewer handoff
artifacts, and reports `local_demo_ready` without network, billing, external
models, or GitHub write permission.
The versioned no-install transcript is available at
[examples/control-plane-demo/demo-output.md](examples/control-plane-demo/demo-output.md),
and tests regenerate it to prevent drift.

PatchRail is published on PyPI, so the fastest install is:

```bash
pipx install patchrail
```

You can also run the latest source directly without installing:

```bash
uvx --from git+https://github.com/patchrail/patchrail patchrail --help
printf 'python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n' \
  | uvx --from git+https://github.com/patchrail/patchrail patchrail ci explain
```

That smoke test prints:

```markdown
# PatchRail CI Report

- Root cause: `python_test_failure`
- Confidence: `0.89`
- Subsystem: Python tests
- Reproduce: `python -m pytest -q`
- Suggested action: Reproduce the failing test, patch the narrow behavior drift, and rerun the focused pytest node before broad test runs.
- Guide: https://getpatchrail.com/fix/python-test-failure?utm_source=cli&utm_campaign=python-test-failure
- Pack: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=python-test-failure
- Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-test-failure

## Evidence signals

- `\bpytest\b`
- `FAILED .*::`
- `AssertionError`

## Safety

PatchRail classified this log locally. It did not create a pull request, post a comment, claim funding, or send data to an external service.
```

Or install the current PyPI package in an isolated virtual environment:

```bash
python3 -m venv .patchrail-wheel-smoke
. .patchrail-wheel-smoke/bin/activate
python -m pip install patchrail==0.1.1
patchrail --help
```

After installation, run the local safety check and classify a failed CI log:

```bash
patchrail doctor
patchrail ci explain --log failed-github-actions.log
```

From a source checkout, use the bundled fixture:

```bash
uv run --extra dev patchrail doctor
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log
```

The same versioned demo can be regenerated locally with:

```bash
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
```

Example output:

```markdown
# PatchRail CI Report

- Root cause: `python_dependency_resolution`
- Confidence: `0.95`
- Subsystem: Python dependency installation
- Reproduce: `python -m pip install -r requirements.txt`
- Suggested action: Pin or relax the conflicting dependency range, then rerun
  the same install command and the affected tests.
- Guide: https://getpatchrail.com/fix/python-dependency-resolution?utm_source=cli&utm_campaign=python-dependency-resolution
- Pack: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=python-dependency-resolution
- Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-dependency-resolution
```

Every `ci explain` report ends with a `Guide:` link to the matching
[getpatchrail.com/fix](https://getpatchrail.com/fix?utm_source=cli) remediation
page and a `Pack:` link to the companion field guide, so the same command that
classifies a failure also points to the full write-up and the downloadable
checklist pack.

## GitHub Action

Drop the same triage into any workflow with
[`patchrail/ci-triage-action`](https://github.com/patchrail/ci-triage-action).
On a red run it classifies the log locally and links the matching
[getpatchrail.com/fix](https://getpatchrail.com/fix) guide — no PR, no comment,
nothing leaves the runner:

```yaml
- name: PatchRail CI triage
  if: failure()
  uses: patchrail/ci-triage-action@v1
  with:
    log-path: test.log
```

The reusable snippet and report artifact shape live in
[examples/ci-triage-action](examples/ci-triage-action/README.md), with links back
to the `/fix` guides and CI Triage field guide using the action campaign.

## Why maintainers use PatchRail

- Turn long CI logs into concise root-cause reports.
- Keep CI log processing local by default.
- Emit Markdown for humans and JSON for automation.
- Preserve a human approval boundary for write actions.
- Use the classifier as a building block for reviewable agent workflows.

## Current scope

| Area | Status | Notes |
| --- | --- | --- |
| CI failure triage | Beta | GitHub Actions-style logs and common open-source toolchains |
| Markdown/JSON reports | Beta | Suitable for local review or manually pasted reports |
| Local queue/control plane | Experimental | SQLite-backed work items with human approval states |
| Funded issue discovery | Planned | Read-only, later, and explicitly anti-abuse |

## Safety

PatchRail is local-first. The CI classifier does not require billing, a GitHub
App, repo write permissions, or an external model call. Write actions are outside
the v0.1 scope and must remain human-approved.

Redact logs before sharing fixtures or reports:

```bash
uv run --extra dev patchrail doctor --format markdown
uv run --extra dev patchrail redact --log failed.log > failed.redacted.log
uv run --extra dev patchrail ci explain --redact --log failed.log
uv run --extra dev patchrail ci pilot-pack --log failed.log --out-dir patchrail-pilot-pack
uv run --extra dev patchrail ci pilot-summary --pack patchrail-pilot-pack --ci-provider "GitHub Actions" --toolchain Python
uv run --extra dev patchrail schema ci-result > ci-result.schema.json
uv run --extra dev patchrail ci benchmark examples/ci-triage --format markdown
```

Run the public checks from a fresh checkout:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev patchrail ci benchmark examples/ci-triage --format json
uv run --extra dev patchrail evidence snapshot --format markdown
uv run --extra dev patchrail evidence application-gate --format markdown
uv run --extra dev patchrail evidence application-dossier --format markdown
uv run --extra dev patchrail evidence release-readiness --clean-dist --format markdown
uv run --extra dev patchrail queue policy-scan --format markdown
uv run --extra dev patchrail queue policy-resolve --format markdown
```

See [ETHICS.md](ETHICS.md), [SECURITY.md](SECURITY.md), and
[docs/threat-model.md](docs/threat-model.md).

## Documentation

- [Quickstart](docs/quickstart.md)
- [CI Janitor](docs/ci-janitor.md)
- [CI Failure Zoo](docs/ci-failure-zoo.md)
- [Maintainer pilot guide](docs/pilot-guide.md)
- [Consent-only pilot request package](docs/pilot-request-package.md)
- [Consent-only pilot outcome example](examples/pilot-outcome/README.md)
- [Adopters](ADOPTERS.md)
- [Metrics](docs/metrics.md)
- [GitHub Actions CI triage](docs/github-action.md)
- [Agent Control Plane](docs/agent-control-plane.md)
- [Agent Control Plane demo transcript](examples/control-plane-demo/README.md)
- [API reference](docs/api-reference.md)
- [Codex workflows](docs/codex-workflows.md)
- [Reviewable automation workflows](docs/agent-workflows.md)
- [Public maintenance workflow ledger](docs/public-workflow-ledger.md)
- [Agent skills](.agents/skills)
- [Threat model](docs/threat-model.md)
- [Funded issue ethics](docs/funded-issues-ethics.md)
- [Roadmap](docs/roadmap.md)
- [Release process](docs/release-process.md)
- [v0.1.0 release evidence](docs/release-v0.1.0-evidence.md)
- [v0.2.0 release evidence](docs/release-v0.2.0-evidence.md)
- [v0.3.0 release evidence](docs/release-v0.3.0-evidence.md)
- [v0.4.0 release evidence](docs/release-v0.4.0-evidence.md)
- [Codex for Open Source evidence](docs/openai-open-source-evidence.md)
- [Open source evidence tracker](docs/open-source-program-evidence.md)

## Contributing

The easiest contribution is a sanitized CI failure fixture. See
[CONTRIBUTING.md](CONTRIBUTING.md) and the
[maintainer pilot guide](docs/pilot-guide.md).
If you are not opening a pull request yet, use the
[CI failure fixture issue template](.github/ISSUE_TEMPLATE/ci_failure_fixture.md)
with a redacted log excerpt and the `fixture-check` result.

If you are testing PatchRail on a repository you maintain, use the adopter
report issue template. `patchrail ci pilot-pack` creates a local redacted pack
for that review path. `patchrail ci pilot-summary` creates a safe outcome
snippet and keeps repository names private unless
`--repository-mention-approved yes` is set. Public adopter listings require
explicit permission. The
[consent-only pilot request package](docs/pilot-request-package.md) has a
copyable maintainer checklist and intake rules for pilots that should become
public evidence.

When you have multiple reviewed summaries, aggregate them without exposing
private repository names:

```bash
uv run --extra dev patchrail ci pilot-metrics pilot-summary-*.json --format markdown
```

To refresh the local evidence view across CI Janitor, the read-only action,
Agent Control Plane, Funded Issue Scout, release evidence, and adopter gaps:

```bash
uv run --extra dev patchrail evidence snapshot --format markdown
```

Before drafting an external program application, run the fail-closed gate:

```bash
uv run --extra dev patchrail evidence application-gate --format markdown
uv run --extra dev patchrail evidence application-dossier --format markdown
```

The gate exits non-zero until PyPI telemetry, permissioned external evidence,
and visible review links are real rather than placeholder-derived.
The dossier command compiles local evidence, upstream contribution links,
blocked dependencies, reviewer_quick_checks, and the submission policy, but it
does not submit the application and keeps maintainer tap required. The quick
checks include the 10-second no-install demo, the pre-PyPI source install
smoke, the fail-closed application gate, and the local application dossier; all
but the optional GitHub source install run without network access or write
actions.

## License

Apache-2.0.
