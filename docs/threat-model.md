# Threat Model

## Assets

- CI logs that may contain secrets.
- Repository names and private paths.
- Maintainer write permissions.
- Release and package publishing credentials.

## v0.1 trust boundary

PatchRail v0.1 runs locally and classifies logs with local rules. It does not
need a GitHub token, billing account, external model, webhook, or GitHub App for
local classification.

## Main risks

| Risk | Mitigation |
| --- | --- |
| Secret leakage in shared logs | Run `patchrail redact` before publishing fixtures |
| Overconfident repair suggestions | Unknown or low-signal failures are triage-only |
| Unapproved repository writes | v0.1 has no write actions |
| Abuse against third-party repos | No auto-commenting, auto-PR, or auto-claim behavior |

## Redaction scope

PatchRail v0.1 redacts common GitHub-style tokens, generic secret assignments,
bearer tokens, API-key-shaped values, email addresses and home-directory paths.
It is a safety layer, not a guarantee that arbitrary logs are safe to publish.

## Future work

- Expand JSON schemas as queue/control-plane outputs become public.
- Add explicit approval gates for any future write-capable workflow.
