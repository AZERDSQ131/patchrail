<!-- Canonical: https://getpatchrail.com/fix/artifact-or-cache-failure -->

# Artifact and cache failures — No files were found with the provided path

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/artifact-or-cache-failure](https://getpatchrail.com/fix/artifact-or-cache-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
No files were found with the provided path
an artifact with this name already exists
Failed to CreateArtifact
Cache service responded with 503
reserveCache failed
```

## What actually happened

The artifact/cache storage layer failed, for one of four reasons: a wrong path ("No files were found with the provided path" — the build put output somewhere else, or the build silently produced nothing), a name collision ("an artifact with this name already exists" — classic in matrix jobs all uploading "build"), a stale action version (v3→v4 of the artifact actions changed naming semantics and broke many pipelines), or a transient storage outage ("Cache service responded with 503"). Crucially, cache restore failures are non-fatal by design — a failed restore should slow the build down, never break it. If a failed restore breaks your build, the build has a hidden dependency on cache contents, and that's the real bug.

## Fix it

1. Identify which of the four causes you have from the signature.
2. Wrong path: add ls -laR <path> just before the upload step. Nine times out of ten the build output simply isn't where the workflow thinks it is.
3. Name collision in a matrix: suffix the artifact name with matrix variables — name: build-${{ matrix.os }}-${{ matrix.version }}.
4. Storage 5xx: retry. It's their outage, not your bug.
5. Bump pinned actions/upload-artifact / actions/download-artifact / actions/cache versions if they're more than a major behind. Do not change application code for this class.

## Prevent it

- Treat cache as an optimization, never a dependency: every job must pass from a cold cache. Test it occasionally by changing the cache key prefix.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=artifact-or-cache-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
