# Funded Issues Ethics

Funded issue discovery is not part of the v0.1 public feature set. It is listed
on the roadmap because funding can be a useful sustainability signal for open
source maintenance when handled carefully.

## Policy

Any future funded issue feature must be read-only by default.

PatchRail must not:

- claim rewards automatically;
- rank work only by funding amount;
- mass-comment on third-party issues;
- submit automatic pull requests to repositories without maintainer permission;
- bypass platform limits or project contribution rules;
- encourage low-quality contributions for payout capture.

## Intended Use

The intended future use is contribution readiness, not bounty farming:

- identify funded maintenance areas;
- explain project contribution rules;
- warn when an issue is likely to attract spam;
- help maintainers understand where work is funded;
- help contributors decide whether they can contribute meaningfully.

## Default Boundary

If this feature is added, the safe default should be local output only:

```bash
patchrail funded-issues list --safe-only --format json
```

No comment, pull request, claim or contact action should happen from that
command. Any write-capable integration must be a separate human-approved path.
