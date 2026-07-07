<!-- Canonical: https://getpatchrail.com/fix/network-transient-failure -->

# Transient network failures — ECONNRESET / EAI_AGAIN / 5xx

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/network-transient-failure](https://getpatchrail.com/fix/network-transient-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
getaddrinfo EAI_AGAIN
Connection reset by peer
ETIMEDOUT
429 Too Many Requests
503 Service Unavailable
```

## What actually happened

Something between the runner and an upstream service failed: DNS (EAI_AGAIN, ENOTFOUND), TCP (ECONNREFUSED, ECONNRESET), TLS handshakes, or the service itself (429, 502, 503, 504). The git-flavored ones (RPC failed, early EOF, fetch-pack: unexpected disconnect) are large-clone failures over flaky connections. This is the most common failure class in real pipelines, and the most commonly mis-triaged: an ECONNRESET during npm install is not an npm problem.

## Fix it

1. Retry once. Genuinely transient failures clear on retry — that's the test.
2. If it recurs, identify which host failed and probe it from the runner environment (curl -sSfI <url>), not from your laptop — CI egress rules differ.
3. 429 / API rate limit exceeded: you're hammering a registry or API from a shared CI IP. Authenticate the request (authenticated rate limits are much higher) or add a backoff.
4. Persistent failures to one host: pin a mirror or proxy through a registry cache.
5. Wrap only the flaky step in a bounded retry (e.g. 3 attempts, exponential backoff). Never blanket-retry the whole job — that hides real failures.

## Prevent it

- Cache dependencies so installs don't touch the network on every run. The fastest network call is the one you don't make.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
