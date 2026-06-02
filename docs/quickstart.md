# Quickstart

Install PatchRail from a checkout:

```bash
uv run --extra dev patchrail --help
```

Confirm the local installation and safety boundary:

```bash
uv run --extra dev patchrail doctor
```

Classify the bundled fixture:

```bash
uv run --extra dev patchrail ci classify --log examples/ci-triage/dependency-failure.log --format json
```

Render a maintainer-readable report:

```bash
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
```

Redact a log before sharing it:

```bash
uv run --extra dev patchrail redact --log examples/ci-triage/dependency-failure.log
```

Check the fixture benchmark:

```bash
uv run --extra dev patchrail ci benchmark examples/ci-triage --format markdown
```

PatchRail v0.1 does not create pull requests, comments, funded issue claims, or
remote uploads. The command reads a local log file and writes a local report.
