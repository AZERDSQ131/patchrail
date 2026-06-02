# Open Source Program Evidence

This page tracks public evidence needed before applying to selective open-source
support programs. Do not submit an application from placeholder metrics.

## Repository Role

Pablo Guillén is the primary maintainer of PatchRail.

## Usage Signals

- GitHub stars: pending public launch
- Monthly PyPI downloads: pending public launch
- External repositories using PatchRail: pending pilots
- External contributors: pending public launch
- Public CI fixtures: 20 sanitized synthetic fixtures in the local benchmark

## Maintenance Workflows

PatchRail's public safety posture is local-first and human-approved:

- CI failure triage produces Markdown, JSON or text reports.
- Redaction runs locally before fixture sharing.
- `patchrail doctor` reports that v0.1 requires no billing, network, external model, or GitHub write permission.
- Write actions are outside v0.1 scope.
- Future agent workflows must use human approval gates.

## Local Release Evidence

Last verified: 2026-06-02.

- Tests: `uv run --extra dev pytest -q` -> 13 passed.
- Lint: `uv run --extra dev ruff check .` -> all checks passed.
- CI benchmark: `uv run --extra dev patchrail ci benchmark examples/ci-triage --format json` -> 20/20 fixtures passed.
- Safety doctor: `uv run --extra dev patchrail doctor --format json` -> `status: ok`, `local_first: true`, and no billing, network, external model, or GitHub write permission required.
- Distribution check: `uv run --extra dev python -m build` produced wheel and sdist; `uv run --extra dev twine check dist/*` passed both artifacts.

## Evidence To Add Before Applying

- PR review examples for parser, redaction or workflow changes.
- Issue triage examples for CI fixture requests.
- Release-prep examples showing changelog, version and quickstart checks.
- Links to releases, PyPI stats and adopter feedback.

## Safety Posture

- No automatic bounty claiming.
- No mass comments.
- No automatic pull requests to third-party repositories.
- Local CI log processing by default.
- Redaction guidance in README, quickstart and threat model.
