# Reproducible CI Triage Demo

This is the real Markdown output from the bundled dependency-resolution fixture:

```bash
uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown
```

```markdown
# PatchRail CI Report

- Root cause: `python_dependency_resolution`
- Confidence: `0.95`
- Subsystem: Python dependency installation
- Reproduce: `python -m pip install -r requirements.txt`
- Suggested action: Pin or relax the conflicting dependency range, then rerun the same install command and the affected tests.
- Guide: https://getpatchrail.com/fix/python-dependency-resolution?utm_source=cli&utm_campaign=python-dependency-resolution
- Pack: https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=python-dependency-resolution
- Free sample: https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=python-dependency-resolution
- Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-dependency-resolution

## Evidence signals

- `Could not find a version that satisfies the requirement`
- `Cannot install .*because these package versions have conflicting dependencies`
- `ResolutionImpossible`
- `python -m pip install`

## Safety

PatchRail classified this log locally. It did not create a pull request, post a comment, claim funding, or send data to an external service.
```
