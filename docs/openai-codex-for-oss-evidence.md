# Codex for Open Source Evidence

This page tracks the evidence PatchRail needs before applying to OpenAI's Codex
for Open Source program. Do not submit an application from placeholder metrics.

## Repository Role

Pablo Guillén is the primary maintainer of PatchRail.

## Usage Signals

- GitHub stars: pending public launch
- Monthly PyPI downloads: pending public launch
- External repositories using PatchRail: pending pilots
- External contributors: pending public launch
- Public CI fixtures: 20 sanitized synthetic fixtures in the local benchmark

## Codex Workflows In Use

Current public evidence is local and preparatory:

- PR review: pending public PR history
- Issue triage: pending public issue history
- Release automation: pending release-prep PR
- CI triage: local workflow and fixture benchmark are ready for public runs

PatchRail's intended Codex usage is bounded to maintainer-approved work:

- PR review for parser, redaction, workflow, and release changes
- issue triage for CI classifier bugs and fixture requests
- CI-failure fix proposals after PatchRail emits a local report
- release-prep checks for changelog, version, docs, and package artifacts

## Local Release Evidence

Last verified: 2026-06-02.

- Tests: `uv run --extra dev pytest -q` -> 13 passed.
- Lint: `uv run --extra dev ruff check .` -> all checks passed.
- CI benchmark: `uv run --extra dev patchrail ci benchmark examples/ci-triage --format json` -> 20/20 fixtures passed.
- Safety doctor: `uv run --extra dev patchrail doctor --format json` -> `status: ok`, `local_first: true`, and no billing, network, external model, or GitHub write permission required.
- Distribution check: `uv run --extra dev python -m build` produced wheel and sdist; `uv run --extra dev twine check dist/*` passed both artifacts.

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
