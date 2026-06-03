# Quickstart

Install PatchRail:

```bash
pipx install patchrail
patchrail --help
```

Confirm the local installation and safety boundary:

```bash
patchrail doctor
```

Install PatchRail from a checkout:

```bash
python -m pip install -e ".[dev]"
```

Classify a failed CI log:

```bash
patchrail ci explain --log failed-github-actions.log
```

Classify the bundled fixture:

```bash
patchrail ci classify --log examples/ci-triage/dependency-failure.log --format json
```

Render a maintainer-readable report:

```bash
patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
```

Redact a log before sharing it:

```bash
patchrail redact --log examples/ci-triage/dependency-failure.log
```

Check the fixture benchmark:

```bash
patchrail ci benchmark examples/ci-triage --format markdown
```

Queue a local CI result for human approval:

```bash
patchrail ci classify --log examples/ci-triage/dependency-failure.log --format json --out patchrail-result.json
patchrail queue from-ci-result --result patchrail-result.json --source examples/ci-triage/dependency-failure.log
patchrail queue list
```

PatchRail v0.1 does not create pull requests, comments, funded issue claims, or
remote uploads. The command reads a local log file and writes a local report.
