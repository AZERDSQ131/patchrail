# Security Policy

## Supported versions

PatchRail is pre-1.0. Security fixes are released on the latest minor version.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting when available. If that is not
available, contact PatchRail through the repository's listed security contact.

Do not paste secrets, private CI logs, access tokens, customer data, or private
repository names into public issues.

## Log safety

CI logs can contain tokens, internal paths, hostnames, package registry URLs, and
deployment metadata. PatchRail v0.1 processes logs locally and does not send them
to a remote service by default.

Before sharing a log fixture publicly:

1. Remove tokens and credentials.
2. Replace private user, org, repo, and host names.
3. Normalize local file paths.
4. Keep only the smallest excerpt needed to classify the failure.
