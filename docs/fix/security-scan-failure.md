<!-- Canonical: https://getpatchrail.com/fix/security-scan-failure -->

# Security scan failures — CVE / GHSA / Severity HIGH

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/security-scan-failure](https://getpatchrail.com/fix/security-scan-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
found 3 high severity vulnerabilities
CVE-2024-12345
GHSA-abcd-efgh-ijkl
RUSTSEC-2024-0001
Severity: CRITICAL
```

## What actually happened

A scanner found a known vulnerability (advisory IDs: CVE-, GHSA-, RUSTSEC-) in a dependency, or a static analyzer (gosec, bandit, semgrep) flagged a code pattern. Two structurally different cases: dependency audits (npm audit, pip-audit, cargo audit, trivy, snyk) fail when a new advisory is published — your build can go red with zero changes on your side, on a Friday, reliably; code scanners flag patterns in code you actually changed. For dependency findings the key question is reachability: is the vulnerable function actually called in your usage? That determines urgency, though gated builds need the finding resolved either way.

## Fix it

1. Identify the advisory and the path to the vulnerable package (npm ls <pkg>, pip-audit output, cargo tree -i <crate>). Direct dependency → upgrade it. Transitive → upgrade the parent, or use an override/resolution to force the patched version.
2. Check the advisory's "patched versions" field — the fix is often a patch-level bump away, the cheapest possible fix.
3. No patch exists yet: assess reachability honestly. If unreachable or not applicable to your usage, record a scoped, expiring ignore (most scanners support ignore-with-expiry files) with the advisory ID and a review date — not a permanent silence.
4. Code-scanner findings (bandit/gosec/semgrep): treat severity HIGH/CRITICAL as a bug report. False positive → suppress at the line with the rule ID and a reason.
5. Rerun the same scanner at the same version before pushing.

## Prevent it

- Run dependency audits on a schedule (daily) separate from PR CI, with alerts to a channel. New-advisory noise then lands on the schedule, not on whichever innocent PR happened to run first.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
