# GitHub Actions Artifact Example

This directory shows the files uploaded by the read-only
`PatchRail CI Triage` workflow artifact.

The workflow uploads the directory as an artifact named
`patchrail-ci-triage`:

```text
patchrail-ci-triage/
|-- ci-report.md
|-- ci-result.json
|-- doctor.json
`-- fixture-benchmark.json
```

The example is generated from
`examples/ci-triage/dependency-failure.log` with local commands equivalent to
the workflow:

```bash
mkdir -p patchrail-report
uv run patchrail ci explain --redact --log examples/ci-triage/dependency-failure.log --format markdown --out patchrail-report/ci-report.md
uv run patchrail ci classify --redact --log examples/ci-triage/dependency-failure.log --format json --out patchrail-report/ci-result.json
uv run patchrail ci benchmark examples/ci-triage --format json --out patchrail-report/fixture-benchmark.json
uv run patchrail doctor --format json --out patchrail-report/doctor.json
```

## Safety Boundary

- The artifact is a report only.
- It does not comment on issues or pull requests.
- It does not open pull requests.
- It does not push commits.
- It does not call external models.
- It does not require billing, network access for classification, or GitHub
  write permissions.

`doctor.json` and `fixture-benchmark.json` use sanitized relative paths in this
example so the public fixture does not expose maintainer machine paths.
