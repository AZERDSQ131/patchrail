# Codex for Open Source Evidence

This page tracks the evidence PatchRail needs before applying to OpenAI's Codex
for Open Source program. Do not submit an application from placeholder metrics.

## Repository Role

Pablo Guillén is the primary maintainer of PatchRail.

## Usage Signals

- Repository: <https://github.com/patchrail/patchrail>
- GitHub stars: 0 on 2026-06-03, immediately after public launch
- Monthly PyPI downloads: pending first PyPI release
- External repositories using PatchRail: pending pilots
- External contributors: pending external contributions
- Public CI fixtures: 40 sanitized synthetic fixtures in the local benchmark
- Public issue queue: 5 launch issues for fixtures, contribution docs, release-prep evidence, and CI maintenance

## Codex Workflows In Use

Current public evidence is local and preparatory:

- PR review: pending public PR history
- Issue triage: launch issue queue created for fixture and docs work
- Release automation: first release-prep checklist is documented in
  [release-process.md](release-process.md); public PR history is pending
- CI triage: public CI is green, and the read-only triage workflow is installed for failed CI runs
- Agent control plane: experimental local SQLite queue added for human-gated maintainer work items

PatchRail's intended Codex usage is bounded to maintainer-approved work:

- PR review for parser, redaction, workflow, and release changes
- issue triage for CI classifier bugs and fixture requests
- CI-failure fix proposals after PatchRail emits a local report
- release-prep checks for changelog, version, docs, and package artifacts

## Local Release Evidence

Last verified: 2026-06-03.

- Release-prep checklist: [docs/release-process.md](release-process.md) now
  requires test, lint, benchmark, doctor, build, wheel smoke, safety, privacy,
  and public CI evidence before any publish step.
- Manual gates: release tags, PyPI publish, GitHub releases, public
  announcements, and external applications remain explicit maintainer actions.
- Tests: `uv run --extra dev pytest -q` -> 16 passed.
- Lint: `uv run --extra dev ruff check .` -> all checks passed.
- CI benchmark: `uv run --extra dev patchrail ci benchmark examples/ci-triage --format json` -> 40/40 fixtures passed.
- Queue demo: `uv run --extra dev patchrail queue --db /tmp/patchrail-demo.sqlite init` and `patchrail queue add/list/approve/export` run locally with no write actions.
- Agent Control Plane demo:
  [`examples/local-agent-queue`](../examples/local-agent-queue/README.md)
  links `ci explain` to `queue add`, `queue approve`, and `queue export`
  using only local files and SQLite.
- Safety doctor: `uv run --extra dev patchrail doctor --format json` -> `status: ok`, `local_first: true`, and no billing, network, external model, or GitHub write permission required.
- Distribution check: `uv run --extra dev python -m build` produced wheel and sdist; `uv run --extra dev twine check dist/*` passed both artifacts.
- Public CI: <https://github.com/patchrail/patchrail/actions/workflows/ci.yml> runs tests, lint, benchmark and package smoke on every push to `main`.
- Public triage workflow: <https://github.com/patchrail/patchrail/actions/runs/26862165709> -> skipped because the triggering CI run succeeded.

## Public Launch Issues

- <https://github.com/patchrail/patchrail/issues/1> - add more Python dependency-resolution CI fixtures.
- <https://github.com/patchrail/patchrail/issues/2> - add Node and TypeScript CI drift fixtures.
- <https://github.com/patchrail/patchrail/issues/3> - document the contributor path for sanitized CI fixtures.
- <https://github.com/patchrail/patchrail/issues/4> - create the first release-prep evidence checklist.
- <https://github.com/patchrail/patchrail/issues/5> - review GitHub Actions Node 24 compatibility before the runner default changes.
- <https://github.com/patchrail/patchrail/issues/6> - add Agent Control Plane demo flow.

## Safety Posture

- Human approval gates for write actions
- No automatic bounty claiming
- No mass comments
- No automatic pull requests to third-party repositories
- Local CI log processing by default
- Redaction guidance in README, quickstart, and threat model

## Evidence To Add Before Applying

- Public PR links reviewed with Codex
- Public issues triaged with Codex
- Release-prep PR prepared with Codex
- Release links
- PyPI download stats
- External adopter feedback
