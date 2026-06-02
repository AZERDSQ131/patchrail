# Release Process

PatchRail uses semantic versioning while the public API stabilizes.

## Before Release

- All tests pass.
- Lint and format checks pass.
- README quickstart works from a clean checkout.
- Changelog is updated.
- Version is updated in `pyproject.toml`.
- Fixtures and expected output are updated when classifier logic changes.
- Security and ethics docs are reviewed when workflows change.

## Local Checks

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev patchrail ci benchmark examples/ci-triage --format json
uv run --extra dev python -m build
uv run --extra dev twine check dist/*
python -m venv .pkg-smoke
. .pkg-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install dist/*.whl
patchrail doctor --format json
patchrail ci explain --log examples/ci-triage/dependency-failure.log --format text
deactivate
```

## Manual Publish Gate

Publishing is a maintainer action. Do not publish packages, create tags or push
release commits from an automated workflow without explicit maintainer approval.

## After Release

- Verify install from the released artifact.
- Create release notes from `CHANGELOG.md`.
- Link any classifier, redaction or docs changes.
- Update docs if the quickstart changed.
