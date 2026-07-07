<!-- Canonical: https://getpatchrail.com/fix/docker-build-failure -->

# Docker image build failures — failed to solve / failed to compute cache key

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/docker-build-failure](https://getpatchrail.com/fix/docker-build-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
failed to solve
failed to compute cache key
target stage could not be found
manifest unknown: manifest not found
service db is unhealthy
```

## What actually happened

BuildKit's "failed to solve" is a wrapper — the real cause is the line after it. The recurring four: (1) "failed to compute cache key" + "/x: not found" — a COPY source doesn't exist in the build context, usually because .dockerignore excludes it or CI builds from a different context directory than you do locally; (2) "target stage ... could not be found" — a typo'd or renamed FROM ... AS <stage> vs --target <stage>; (3) "manifest ... not found" — the base image tag doesn't exist (deleted upstream, or no build for your platform — check --platform on multi-arch); (4) "service ... is unhealthy" — compose-specific: the image built fine but a healthcheck never went green, so the real log is the service's log, not the build log.

## Fix it

1. Read the line after failed to solve — that's the actual error.
2. COPY failures: print the context as CI sees it (ls -la in the same directory the build runs from) and check .dockerignore. The file exists in the repo; it doesn't exist in the context.
3. manifest not found: confirm the tag exists for your platform (docker manifest inspect <image>); pin a digest if the tag churns.
4. service is unhealthy: get the service's own output (docker compose logs <service>) and triage that — the compose error is just the timeout notification. Check the healthcheck timing.
5. Reproduce locally with the same context dir, same --target, same --platform as CI before touching the Dockerfile.

## Prevent it

- Pin base images by digest (FROM image@sha256:...) for anything that ships; tags are mutable and latest is a time bomb.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
