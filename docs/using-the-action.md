# Using the CI triage action in your own repository

`docs/github-action.md` documents the triage workflow that runs inside the
PatchRail repository itself. This page is for the more common case: you
maintain a different repository and want the
[`patchrail/ci-triage-action`](https://github.com/patchrail/ci-triage-action)
step in your own workflow.

## 1. Capture the failing log to a file

The action reads a log file from disk — it does not capture your test
runner's output for you. Redirect or `tee` the command that can fail so a
`.log` file exists when the step runs:

```yaml
- name: Run tests
  run: pytest -q 2>&1 | tee test.log
```

`tee` keeps the log visible in the live job output while also writing it to
`test.log`, so `if: failure()` steps later in the job can read it.

## 2. Add the triage step

```yaml
- name: PatchRail CI triage
  if: failure()
  uses: patchrail/ci-triage-action@v1
  with:
    log-path: test.log
```

Inputs:

| Input | Required | Default | Description |
|-------|----------|---------|--------------|
| `log-path` | yes | — | Path to the failed CI log inside the checked-out repository. |
| `report-dir` | no | `patchrail-ci-triage` | Directory where the action writes the Markdown and JSON reports. |
| `redact` | no | `true` | Redact secrets, emails, and local home paths before writing reports. |

`if: failure()` is what makes this a triage-on-red step: it only runs after
a prior step in the same job has failed, so `log-path` points at a log that
already contains the failure.

## 3. What you get on a red run

The action classifies the log locally and exposes the result two ways —
there is no run annotation; look in the step's own outputs and the job
summary.

### Step outputs

Reference these from a later step with
`${{ steps.<step-id>.outputs.<name> }}`:

| Output | Description |
|--------|--------------|
| `failure-class` | PatchRail failure class for the CI log. |
| `failure-slug` | URL-safe version of the failure class, for labels and artifact names. |
| `confidence` | Classifier confidence, `0`-`1`. |
| `json-result` | Path to the structured PatchRail result JSON. |
| `markdown-report` | Path to the maintainer-readable PatchRail report. |
| `artifact-name` | Stable artifact name for uploading the triage bundle. |
| `summary-line` | One-line triage summary, the same text written to the job summary. |
| `redacted-categories` | Number of local redaction categories found in the log. |
| `next-step` | Minimal next repair step for the detected failure. |
| `reproduction-command` | Local command PatchRail recommends to reproduce the failure. |
| `adoption-key` | Stable key for this failure class, for downstream adoption dashboards. |
| `adoption-event-id` | Stable per-run/per-job event id, for deduplicating evidence. |
| `adoption-event-json` | Single-line adoption event JSON, appendable to an evidence ledger. |
| `workflow-repository`, `workflow-run-url`, `workflow-run-host` | Attribution for the run that produced the triage, when available. |

Give the step an `id` to reference these:

```yaml
- name: PatchRail CI triage
  id: triage
  if: failure()
  uses: patchrail/ci-triage-action@v1
  with:
    log-path: test.log

- name: Label the issue with the failure class
  if: failure()
  run: echo "Detected ${{ steps.triage.outputs.failure-class }} (confidence ${{ steps.triage.outputs.confidence }})"
```

### Job summary

The action appends a section to the job's `GITHUB_STEP_SUMMARY`, visible on
the workflow run page without opening any artifact:

```markdown
## PatchRail CI triage

- Summary: PatchRail CI triage: python_dependency_resolution (0.95)
- Next step: Pin or relax the conflicting dependency range, then rerun the same install command and the affected tests.
- Adoption key: `ci-triage:python-dependency-resolution`
- Adoption event ID: `ci-triage-run:owner/repo:123456:triage:python-dependency-resolution`
- Redacted categories: `0`
- Report: `patchrail-ci-triage/ci-report.md`
- Workflow run: https://github.com/owner/repo/actions/runs/123456
```

### Report files

By default under `patchrail-ci-triage/` (or wherever `report-dir` points):

- `ci-report.md` — the Markdown report also referenced by `markdown-report`.
- `ci-result.json` — the structured `patchrail.ci_result.v1` result also
  referenced by `json-result`. See the
  [jq cookbook](json-cookbook.md) for scripting against it.

Upload it as a workflow artifact if you want it downloadable from the run:

```yaml
- name: Upload PatchRail report
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: ${{ steps.triage.outputs.artifact-name }}
    path: patchrail-ci-triage/
```

## 4. Permissions and privacy

The action only needs read access to the repository checkout it runs in:

```yaml
permissions:
  contents: read
```

It does not need `actions: read`, `issues: write`, `pull-requests: write`, or
any GitHub token beyond the default. Classification runs entirely on the
runner against the log file you point it at — nothing is uploaded to
PatchRail, no external model is called, and the action does not comment on
issues, open pull requests, or push commits. See `docs/threat-model.md` for
the full local trust boundary.

## Pinning the action version

Pin to a released tag (or a commit SHA, for maximum reproducibility) the same
way you would pin any other action:

```yaml
uses: patchrail/ci-triage-action@v1        # tag
uses: patchrail/ci-triage-action@<full-sha> # commit
```

There is no separate PatchRail-version input — pinning the action ref pins
the PatchRail version it installs.

## Full example

```yaml
name: CI

on: [push, pull_request]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Run tests
        run: pytest -q 2>&1 | tee test.log
      - name: PatchRail CI triage
        id: triage
        if: failure()
        uses: patchrail/ci-triage-action@v1
        with:
          log-path: test.log
      - name: Upload PatchRail report
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: ${{ steps.triage.outputs.artifact-name }}
          path: patchrail-ci-triage/
```

See [`examples/ci-triage-action`](../examples/ci-triage-action/README.md) for
a reproducible sample of the exact artifact shape (`ci-result.json`,
`ci-report.md`, `github-output.txt`, `step-summary.md`) and
`docs/github-action.md` for how PatchRail uses this same action against its
own `CI` workflow.
