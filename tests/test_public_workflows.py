from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_triage_workflow_is_read_only_and_human_reviewed() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci-triage.yml").read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "uv run patchrail ci explain --redact" in workflow
    assert "uv run patchrail ci classify --redact" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "gh pr create" not in workflow
    assert "gh issue comment" not in workflow


def test_github_action_docs_preserve_safety_boundary() -> None:
    docs = (ROOT / "docs" / "github-action.md").read_text(encoding="utf-8")

    assert "does not comment on issues or pull requests" in docs
    assert "does not open pull requests" in docs
    assert "does not call external models" in docs
    assert "contents: read" in docs
    assert "actions: read" in docs


def test_oss_plan_canonical_docs_exist_and_preserve_human_gates() -> None:
    codex_workflows = (ROOT / "docs" / "codex-workflows.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/codex-workflows.md" in readme
    assert "docs/openai-codex-for-oss-evidence.md" in readme
    assert "The v0.1 release does not require Codex or any external model" in codex_workflows
    assert "no automatic pull requests" in codex_workflows
    assert "Human approval gates for write actions" in evidence
    assert "No automatic bounty claiming" in evidence


def test_ci_workflow_builds_and_smokes_installable_package() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release_process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")

    assert "package-smoke:" in workflow
    assert "uv run --extra dev python -m build" in workflow
    assert "uv run --extra dev twine check dist/*" in workflow
    assert "python -m venv .pkg-smoke" in workflow
    assert "python -m pip install dist/*.whl" in workflow
    assert "patchrail doctor --format json" in workflow

    assert "python -m pip install dist/*.whl" in release_process
    assert "patchrail ci explain --log examples/ci-triage/dependency-failure.log" in release_process
