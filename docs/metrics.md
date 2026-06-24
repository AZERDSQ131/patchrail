# Metrics

PatchRail tracks adoption and quality metrics so public claims stay verifiable.
Do not use placeholders as evidence for applications, release posts, or funding
requests.

Last updated: 2026-06-24.

## Public Signals

| Metric | Current value | Source |
| --- | ---: | --- |
| GitHub repository | `patchrail/patchrail` | <https://github.com/patchrail/patchrail> |
| GitHub stars | 0 | Fresh public launch snapshot |
| PyPI package | `patchrail` 0.1.1 published | <https://pypi.org/project/patchrail/0.1.1/> |
| Clean PyPI install smoke | Passing on 2026-06-12 | `python -m pip install patchrail==0.1.1`; `patchrail doctor`; stdin `patchrail ci explain` |
| Monthly PyPI downloads | Rolling package telemetry: 154 downloads in the last month, 20 in the last week, and 3 in the last day as of 2026-06-24; `python_major` totals 154 across 2026-06-11..23 | `curl https://pypistats.org/api/packages/patchrail/recent` and `/python_major`; package-level signal only, not version-specific adoption |
| Public external adopters | 0 | [ADOPTERS.md](../ADOPTERS.md) |
| External contributors | 0 | GitHub contributors |
| Public releases | 2 | <https://github.com/patchrail/patchrail/releases/tag/v0.1.1> |
| Public CI fixtures | 153 | `examples/ci-triage` benchmark |
| Fixture hygiene gate | 153 / 153 passing | `patchrail ci fixture-check examples/ci-triage --format json` |
| Supported benchmark categories | Python, Node, TypeScript, Go, Rust, Ruby, PHP, .NET, GitHub Actions, Docker/Compose, browser E2E | `docs/ci-failure-zoo.md` |
| Agent Control Plane demos | 1 | `examples/local-agent-queue` |
| Funded issue read-only demos | 1 | `examples/funded-issues-readonly` |
| Synthetic consent-only pilot examples | 1 | `examples/pilot-outcome` |
| Owned-repo consent-only pilot outcomes | 1 | [patchrail-own-repo-20260603.md](../examples/pilot-outcome/patchrail-own-repo-20260603.md) |
| Active evidence follow-up issues | 1 | [#69](https://github.com/patchrail/patchrail/issues/69) |

## Quality Gates

Before increasing a metric in public docs:

- link the source;
- verify it from a public page, command output, or repository artifact;
- avoid counting private runs as adoption;
- avoid counting unapproved pilot names as adopters;
- keep funded issue metrics separate from CI triage usefulness;
- never report payouts, bounty value, or money-ranked opportunity counts as the
  primary project metric.

To aggregate reviewed consent-only pilot outcomes without exposing unapproved
repository names:

```bash
patchrail ci pilot-metrics pilot-summary-*.json --format markdown
```

To regenerate a local cross-workstream evidence snapshot without network,
external models, billing, or GitHub write permission:

```bash
patchrail evidence snapshot --format markdown
```

The snapshot is a consistency check over the checkout. It does not replace
public GitHub, PyPI, or adopter metrics.

To refresh the live website metric API from local read-only evidence:

```bash
patchrail web-metrics update \
  --web-dir /path/to/getpatchrail.com \
  --product-repo . \
  --desk-dir /path/to/opportunity-desk \
  --format json
```

The command writes three static payloads when evidence changes:

- `public/api/landing-metrics.json` for the homepage counters;
- `public/api/sources-volumes.json` for the sources page;
- `public/api/product-metrics.json` for product readiness, tracker health, and automation status.

The payloads are read-only, local-first, and safe to run from a scheduler. They
do not fetch provider APIs, write to GitHub, contact maintainers, claim bounties,
or deploy production by themselves.

Before applying to an external open-source support program, run the fail-closed
application gate:

```bash
patchrail evidence application-gate --format markdown
```

It exits non-zero until public metrics are real and sufficient: PyPI telemetry,
permissioned external pilots/adopters, and visible review links must exist
before application copy can be treated as ready.

The main CI workflow also publishes this output as the read-only
`patchrail-open-source-evidence` artifact after tests, fixture benchmark, and package
smoke pass. Treat that artifact as reproducible project-health evidence, not as
external adoption or PyPI download evidence.

Use [docs/pilot-request-package.md](pilot-request-package.md) before promoting
any pilot to public evidence. It records the maintainer consent checklist,
evidence intake rules, and `ADOPTERS.md` listing boundary.

Use `patchrail ci pilot-metrics` to aggregate consent-only pilot summaries
before publishing a snapshot:

```bash
patchrail ci pilot-metrics examples/pilot-outcome/*.summary.json --format markdown
```

The command separates owned-repo public mentions from external repository
mentions. Outcomes for `patchrail/*` are project evidence, but they are not
external adopters. Private or unapproved repository names stay private and must
not be counted as public evidence.

## Weekly Snapshot Template

```markdown
## YYYY-Www

- GitHub stars:
- PyPI downloads, last 30 days:
- External repos testing PatchRail:
- External contributors:
- New sanitized fixtures:
- Fixture-check total / passed:
- Benchmark total / passed:
- Issues opened / closed:
- PRs opened / merged:
- Codex-reviewed PRs:
- Codex-triaged issues:
- Consent-only pilot summaries:
- Public repository mentions approved:
- Owned-repo public mentions:
- External public repository mentions:
- Countable external adopters:
- Release or package status:
- Notable maintainer feedback:
```

## Evidence Before Applying

PatchRail should not apply to external programs from placeholder metrics. The
current evidence gaps are:

- first full 30-day PyPI download window after the published 0.1.1 package;
- external maintainer pilots with permission to cite outcomes;
- consent checklist coverage from [docs/pilot-request-package.md](pilot-request-package.md);
- safe external pilot summaries based on [examples/pilot-outcome](../examples/pilot-outcome/README.md);
- permissioned pilot fixture submissions that pass `fixture-check`;
- public PRs reviewed with Codex;
- public issues triaged with Codex;
- real adopter entries approved for [ADOPTERS.md](../ADOPTERS.md).

Active follow-up issues:

- [#69](https://github.com/patchrail/patchrail/issues/69) for verified adoption and ecosystem signal tracking.

Completed package evidence:

- [#67](https://github.com/patchrail/patchrail/issues/67) records the first
  public PyPI package release and clean install verification for `patchrail==0.1.1`.

Completed pilot evidence:

- [#68](https://github.com/patchrail/patchrail/issues/68) records the first
  owned-repo consent-only pilot outcome for `patchrail/patchrail`. This is a
  real public pilot signal for the project itself, not an external adopter.
