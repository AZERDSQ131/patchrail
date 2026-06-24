# CI Triage Action Snippet

Use this snippet when a workflow already writes a failed CI log to disk and you
want PatchRail to turn that log into a local Markdown and JSON triage report.

```yaml
- name: PatchRail CI triage
  if: failure()
  uses: patchrail/ci-triage-action@v1
  with:
    log-path: test.log
    report-dir: patchrail-ci-triage
```

The action runs inside the GitHub Actions runner, reads the log path you pass in,
and writes:

- `patchrail-ci-triage/ci-report.md`
- `patchrail-ci-triage/ci-result.json`

Reusable outputs include `failure-class`, `failure-slug`, `utm-source`,
`utm-campaign`, `adoption-key`, `adoption-event-json`, `guide-url`, `pack-url`,
`artifact-name`, `next-step`, and `reproduction-command`, so a
downstream workflow can route the failure to a maintainer or attach the local
report to an internal ticket. `adoption-key` is stable across runs of the same
failure class and attribution campaign, which makes real workflow usage countable
without parsing URLs. `adoption-event-json` is a single-line event that can be
appended directly to an evidence ledger artifact.

It does not open pull requests, post comments, claim funding, or send the log to
an external service.

## Reproducible sample

This sample uses `examples/ci-triage/dependency-failure.log` and stores the
same artifact shape the action writes in a workflow:

- [sample/ci-result.json](sample/ci-result.json)
- [sample/ci-report.md](sample/ci-report.md)
- [sample/github-output.txt](sample/github-output.txt)
- [sample/step-summary.md](sample/step-summary.md)

Regenerate it from the repository root:

```sh
uv run patchrail ci classify \
  --log examples/ci-triage/dependency-failure.log \
  --format json \
  --out examples/ci-triage-action/sample/ci-result.json

uv run patchrail ci explain \
  --log examples/ci-triage/dependency-failure.log \
  --format markdown \
  --out examples/ci-triage-action/sample/ci-report.md

: > examples/ci-triage-action/sample/github-output.txt
: > examples/ci-triage-action/sample/step-summary.md
uv run python actions/ci-triage/scripts/ci_triage_action_outputs.py \
  --result examples/ci-triage-action/sample/ci-result.json \
  --report examples/ci-triage-action/sample/ci-report.md \
  --output examples/ci-triage-action/sample/github-output.txt \
  --summary examples/ci-triage-action/sample/step-summary.md
```

The sample links the detected failure to the matching `/fix` guide, the CI
Triage field guide SKU, and the public action distribution surface:

- Fix guide: https://getpatchrail.com/fix/python-dependency-resolution?utm_source=cli&utm_campaign=python-dependency-resolution
- CI Triage field guide: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=python-dependency-resolution
- Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-dependency-resolution

Related PatchRail surfaces:

- Fix guides: https://getpatchrail.com/fix?utm_source=github&utm_campaign=ci-triage-action
- CI Triage field guide: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=ci-triage-action
