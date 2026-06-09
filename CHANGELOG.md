# Changelog

## 0.2.0 - draft

- Added a read-only `assess_bounty_competition` signal to `funded-issues`
  scoring that derives `contested_bounty` / `crowded_no_assignment` risk flags
  from public competition metadata (competing PR count, distinct claimants,
  comment volume, assignment), with curated `CONTESTED_HIGH_COMPETITION` /
  `CROWDED_NO_CLEAR_OWNER` reason codes. Competition flags cost score and
  confidence without forcing an automatic no-go.
- Added `funded-issues competition`, a read-only batch command that scores
  competition / noise-trap pressure across many bounties from public metadata
  observations (JSON list or `{observations: [...]}`), sorts results
  highest-pressure first, and summarizes high/elevated/low counts plus
  contested/crowded totals. Backed by the pure `assess_competition_batch`
  helper and an example observations fixture. Strictly read-only: no claims,
  comments, or maintainer contact.
- Added a read-only `assess_payout_effort` signal to `funded-issues` scoring
  that compares a bounty's public funding amount against an effort estimate and
  a target hourly-rate floor ($150/h default), deriving a
  `payout_too_low_for_effort` risk flag with a curated
  `PAYOUT_TOO_LOW_FOR_EFFORT` reason code. Levels are strong / marginal / low /
  unknown / unverified_currency; the flag costs score without forcing an
  automatic no-go, and non-USD funding is surfaced as unverified rather than
  guessed.
- Added `funded-issues payout-effort`, a read-only batch command that scores
  payout-vs-effort across many bounties from observations (JSON list or
  `{observations: [...]}`), sorts results worst-payout first, and summarizes
  low/marginal/strong/unknown/unverified-currency counts plus an underpaid
  total. Backed by the pure `assess_payout_effort_batch` helper and an example
  observations fixture. Strictly read-only: no claims, comments, or maintainer
  contact.
- Added `funded-issues apply-recheck`, a local-file-only command that applies
  recheck observations (a JSON list, an `{observations: [...]}` object, or a
  list of GitHub API issue objects) to a tracker store, transitioning entries
  to closed / stale / active. Stale is derived from `updated_at` against a
  `--stale-after-days` floor (default 45); `state_history` records only real
  transitions, `--dry-run` reports without writing, and a second identical pass
  is a no-op. Backed by the pure `apply_recheck_to_store` helper and the
  `funded-issues-recheck-summary` schema. Strictly read-only: no claims,
  comments, or maintainer contact.
- Prepared the CI Janitor v0.2 evidence bundle around the 143-case fixture zoo,
  `fixture-check`, read-only GitHub Actions triage artifact, maintainer pilot
  guide, and public metrics/adopter surfaces.
- Added .NET/NuGet/C# and xUnit fixture coverage for `dotnet restore`,
  `dotnet build`, and `dotnet test` failure modes.
- v0.2 remains a maintainer-gated release candidate until the maintainer
  explicitly bumps `pyproject.toml`, tags the release, publishes package
  artifacts, and records final CI/PyPI evidence.

## 0.1.0 - 2026-06-02

- Initial public CI Janitor snapshot.
- Added `patchrail ci explain` and `patchrail ci classify`.
- Added local Markdown, JSON, and text reports.
- Added Apache-2.0 license and safety/ethics documentation.
- Added fixture-backed tests, local benchmark command, and GitHub Actions CI.
- Expanded the initial CI fixture zoo to 101 sanitized synthetic examples across
  Python, Node, TypeScript, Go, Rust, and GitHub Actions failure modes.
- Added a read-only GitHub Actions triage artifact workflow.
- Added the experimental local Agent Control Plane queue with SQLite-backed
  work items, approval states, audit export, CI result import, and proposal
  records.
- Added the experimental read-only `funded-issues` CLI over local metadata,
  with safe-only filtering and explicit anti-abuse blocked actions.
- Added permission-only adopter reporting and a public metrics tracker for
  pilot outcomes, adoption signals, and Codex for open-source evidence gaps.
- Added release-prep evidence docs, package smoke checks, and manual publish
  gates. Release tags, PyPI publishing, GitHub Releases, and public
  announcements remain maintainer actions.
