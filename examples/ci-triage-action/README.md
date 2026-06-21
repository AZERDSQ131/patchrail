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

It does not open pull requests, post comments, claim funding, or send the log to
an external service.

Related PatchRail surfaces:

- Fix guides: https://getpatchrail.com/fix?utm_source=github&utm_campaign=ci-triage-action
- CI Triage field guide: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=ci-triage-action
