# Quickstart

Install PatchRail from a checkout:

```bash
python -m pip install -e ".[dev]"
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

PatchRail v0.1 does not create pull requests, comments, funded issue claims, or
remote uploads. The command reads a local log file and writes a local report.
