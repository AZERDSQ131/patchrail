# Changelog

## 0.2.0 - draft

- `ci explain` now ends every report with a `Guide:` link to the matching
  remediation write-up on getpatchrail.com (`/fix/<failure-class>`, with
  `utm_source=cli`). Unknown or unlisted failure classes link to the `/fix`
  guide index instead. The link appears in both the text and Markdown formats;
  JSON output is unchanged. Classification stays fully local -- the URL is
  constructed from the failure class, with no network call.
- Added a permanent source-level blocklist to the funded-issues tracker:
  owners manually verified as fake-bounty sources are dropped at the
  `merge_into_store` choke point (counted as `blocked` in the merge summary)
  and `purge_blocklisted_entries` removes any legacy entries -- `track` runs
  the purge on every merge so existing stores self-heal. The list is code, not
  config: removing an owner requires a reviewed change.
- Added `funded-issues import-algora-board`, an offline parser for a locally
  saved Algora organization bounty-board page (`https://algora.io/<org>/bounties`).
  It extracts the funder-stated USD amount, GitHub issue reference, posting
  age, and declared claim count per bounty, marks funding as `verified` with
  the board as `evidence_url`, raises `contested_bounty` when declared claims
  reach the competition threshold, and can merge the scored records straight
  into a tracker store (`--store`). The page must be saved locally first: the
  command performs no network access, and the payload reports how many open
  bounties the server-rendered page did not include.
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
- Added an offline owner-level `source_noise` heuristic to `funded-issues`: the
  pure `assess_owner_source_noise` helper screens an owner's public metadata
  (account age, public repos, followers, website, payout verifiability) plus its
  near-identical-issue volume into `noise_flags`, flagging the owner when it
  trips at least two strong signals. `apply_source_noise_to_store` stamps the
  verdict onto store entries via a new `noise_flags` field that survives
  merge/upsert and apply-recheck, and `track-status` / web metrics now report a
  `tracked_total` / `noise_flagged` / `clean_active` breakdown instead of a
  single inflated active count. Strictly read-only: no network, no third-party
  writes.
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
