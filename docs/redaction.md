# Redaction reference

`patchrail redact` and the `--redact` flag on `ci explain`/`ci classify` run
the same set of local regex patterns (`REDACTION_PATTERNS` in
`src/patchrail/ci/classify.py`) over a log before it is shared. This page
lists every category so you can decide whether a redacted log is safe to
share without reading the source.

## What gets redacted

| Category | What it matches | Replacement |
|----------|------------------|-------------|
| `github_token` | GitHub personal access tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`) | `<github-token>` |
| `github_fine_grained_token` | GitHub fine-grained tokens (`github_pat_...`) | `<github-token>` |
| `gitlab_token` | GitLab personal access tokens (`glpat-...`) | `<gitlab-token>` |
| `api_key` | Generic secret/restricted API keys (`sk-...`, `rk-...`) | `<api-key>` |
| `npm_token` | npm auth tokens (`npm_...`) | `<npm-token>` |
| `pypi_token` | PyPI upload tokens (`pypi-...`) | `<pypi-token>` |
| `aws_access_key` | AWS access key IDs (`AKIA...`, `ASIA...`) | `<aws-access-key>` |
| `stripe_secret_key` | Stripe secret keys (`sk_live_...`, `sk_test_...`) | `<stripe-secret-key>` |
| `slack_token` | Slack tokens (`xoxb-`, `xoxp-`, `xoxa-`, `xoxr-`, `xoxs-`) | `<slack-token>` |
| `google_api_key` | Google API keys (`AIza...`) | `<google-api-key>` |
| `google_oauth_token` | Google OAuth access tokens (`ya29....`) | `<google-oauth-token>` |
| `huggingface_token` | Hugging Face tokens (`hf_...`) | `<huggingface-token>` |
| `private_key_block` | PEM private key blocks (RSA, EC, DSA, OpenSSH, PGP) | `<private-key>` |
| `jwt` | JSON Web Tokens (three dot-separated base64url segments starting `eyJ...`) | `<jwt>` |
| `bearer_token` | `Bearer <token>` HTTP authorization headers | `Bearer <token>` |
| `sendgrid_api_key` | SendGrid API keys (`SG....`) | `<sendgrid-api-key>` |
| `telegram_bot_token` | Telegram bot tokens (`<bot-id>:AA...`) | `<telegram-bot-token>` |
| `url_credentials` | `user:password@` embedded in a URL | `<credentials>@` (scheme and host kept) |
| `env_secret_assignment` | `SOME_TOKEN=...`, `SOME_SECRET=...`, `SOME_PASSWORD=...`, `SOME_KEY=...` style assignments | `SOME_TOKEN=<redacted>` (variable name kept) |
| `email` | Email addresses | `<email>` |
| `unix_home_path` | Linux home directories (`/home/<user>/...`) | `/home/<user>` |
| `mac_home_path` | macOS home directories (`/Users/<user>/...`) | `/Users/<user>` |
| `windows_home_path` | Windows home directories (`C:\Users\<user>\...`) | `C:/Users/<user>` |

This table mirrors `REDACTION_PATTERNS` exactly. If you add or change a
pattern in `src/patchrail/ci/classify.py`, update this table in the same pull
request.

## What is not covered

Redaction is a set of known patterns, not a secret scanner. It does **not**
catch:

- Company-internal hostnames, service names, or infrastructure details that
  don't match a known token format.
- Custom or organization-specific secret formats not in the table above.
- Secrets split across multiple lines or wrapped mid-token.
- Free-text mentions of customer names, private repository names, or
  usernames that aren't part of a matched pattern (a home path is redacted,
  but a username typed elsewhere in the log is not).

Because of this, a human review is still required before sharing any log,
redacted or not — consistent with `CONTRIBUTING.md`'s fixture contribution
path and the local trust boundary described in `docs/threat-model.md`.

## Running it

```bash
patchrail redact --log ci.log
```

Add `--format json` to get the redacted text alongside a per-category count:

```bash
patchrail redact --log ci.log --format json
```

```json
{
  "local_only": true,
  "redactions": {
    "email": 1,
    "github_token": 1,
    "unix_home_path": 1
  },
  "schema_version": "patchrail.redaction.v1",
  "text": "token: <github-token> contact <email> in /home/<user>\n"
}
```

The `redactions` map lists each category name from the table above with how
many times it matched. An empty `redactions` map means none of the known
patterns fired — it does not mean the log is free of anything worth
reviewing.

`ci explain --redact` and `ci classify --redact` embed the same shape under
`result.redaction` instead of writing a separate file.

## Verify before sharing checklist

Before attaching a redacted log to an issue, pull request, or pilot pack:

1. Run `patchrail redact --log <file> --format json` and check the
   `redactions` counts look right for what you expect to be in the log.
2. Read the redacted output. Look for anything not in the table above:
   internal hostnames, customer or teammate names, private repository or
   package names, ticket numbers, IP addresses.
3. Trim the log to the smallest excerpt that still shows the failure —
   less text is less to review.
4. If the log came from a real run and cannot be safely redacted, follow
   `CONTRIBUTING.md`'s guidance to build a minimal synthetic fixture instead.
