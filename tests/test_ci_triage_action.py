from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from patchrail.cli import main


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "actions" / "ci-triage" / "action.yml"
HELPER = ROOT / "actions" / "ci-triage" / "scripts" / "ci_triage_action_outputs.py"
FIXTURE = ROOT / "examples" / "ci-triage" / "dependency-failure.log"
ACTION_SNIPPET = ROOT / "examples" / "ci-triage-action" / "README.md"
ACTION_SAMPLE = ROOT / "examples" / "ci-triage-action" / "sample"


def _load_helper():
    spec = importlib.util.spec_from_file_location("ci_triage_action_outputs", HELPER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ci_triage_action_is_local_composite_action() -> None:
    text = ACTION.read_text(encoding="utf-8")

    assert "using: composite" in text
    assert "patchrail ci classify" in text
    assert "patchrail ci explain" in text
    assert "$GITHUB_ACTION_PATH/../.." in text
    assert "failure-class:" in text
    assert "failure-slug:" in text
    assert "utm-source:" in text
    assert "utm-campaign:" in text
    assert "guide-url:" in text
    assert "pack-url:" in text
    assert "action-url:" in text
    assert "artifact-name:" in text
    assert "next-step:" in text
    assert "reproduction-command:" in text
    assert "summary-line:" in text
    assert "redacted-categories:" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_ci_triage_action_distribution_snippet_is_revenue_attributed() -> None:
    text = ACTION_SNIPPET.read_text(encoding="utf-8")

    assert "uses: patchrail/ci-triage-action@v1" in text
    assert "report-dir: patchrail-ci-triage" in text
    assert "utm_source=github&utm_campaign=ci-triage-action" in text
    assert "patchrail.gumroad.com/l/ci-failure-triage" in text
    assert "`next-step`" in text
    assert "`utm-campaign`" in text
    assert "does not open pull requests" in text
    assert "post comments" in text
    assert "send the log to" in text
    assert "an external service" in text
    assert "sample/ci-result.json" in text
    assert "utm_source=cli&utm_campaign=python-dependency-resolution" in text


def test_ci_triage_action_helper_exports_reusable_outputs(tmp_path: Path) -> None:
    result_path = tmp_path / "ci-result.json"
    report_path = tmp_path / "ci-report.md"
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"

    assert (
        main(
            [
                "ci",
                "classify",
                "--log",
                str(FIXTURE),
                "--format",
                "json",
                "--out",
                str(result_path),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "ci",
                "explain",
                "--log",
                str(FIXTURE),
                "--format",
                "markdown",
                "--out",
                str(report_path),
            ]
        )
        == 0
    )

    helper = _load_helper()
    assert (
        helper.main(
            [
                "--result",
                str(result_path),
                "--report",
                str(report_path),
                "--output",
                str(output_path),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    outputs = dict(line.split("=", 1) for line in lines)
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert outputs["failure-class"] == result["failure_class"]
    assert outputs["failure-slug"] == "python-dependency-resolution"
    assert outputs["utm-source"] == "cli"
    assert outputs["utm-campaign"] == "python-dependency-resolution"
    assert outputs["confidence"] == str(result["confidence"])
    assert outputs["guide-url"].startswith("https://getpatchrail.com/fix")
    assert outputs["pack-url"].startswith("https://patchrail.gumroad.com/l/ci-failure-triage")
    assert outputs["action-url"].startswith("https://github.com/patchrail/ci-triage-action")
    assert outputs["next-step"] == result["minimal_repair_strategy"]
    assert outputs["reproduction-command"] == result["reproduction_command"]
    assert outputs["json-result"] == str(result_path)
    assert outputs["artifact-name"] == "patchrail-ci-triage-python-dependency-resolution"
    assert outputs["markdown-report"] == str(report_path)
    assert outputs["summary-line"].startswith("PatchRail CI triage: python_dependency_resolution")
    assert outputs["guide-url"] in outputs["summary-line"]
    assert outputs["redacted-categories"] == "0"

    summary = summary_path.read_text(encoding="utf-8")
    assert "## PatchRail CI triage" in summary
    assert outputs["summary-line"] in summary
    assert outputs["next-step"] in summary
    assert "- Redacted categories: `0`" in summary
    assert str(report_path) in summary


def test_ci_triage_action_helper_exports_index_attribution_for_unlisted_classes() -> None:
    helper = _load_helper()
    outputs = helper.action_outputs(
        {
            "failure_class": "pre_commit_hook_failure",
            "confidence": 0.7,
            "guide_url": "https://getpatchrail.com/fix?utm_source=cli",
            "pack_url": "https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=index",
            "action_url": "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
            "minimal_repair_strategy": "Run the hook locally.",
            "reproduction_command": "pre-commit run --all-files",
        },
        Path("ci-result.json"),
        Path("ci-report.md"),
    )

    assert outputs["failure-slug"] == "pre-commit-hook-failure"
    assert outputs["utm-source"] == "cli"
    assert outputs["utm-campaign"] == "index"


def test_ci_triage_action_helper_counts_redacted_categories(tmp_path: Path) -> None:
    helper = _load_helper()
    result = {
        "failure_class": "python_test_failure",
        "confidence": 0.9,
        "guide_url": "https://getpatchrail.com/fix/python-test-failure?utm_source=cli",
        "pack_url": "https://patchrail.gumroad.com/l/ci-failure-triage",
        "action_url": "https://github.com/patchrail/ci-triage-action",
        "minimal_repair_strategy": "Rerun pytest locally.",
        "reproduction_command": "pytest tests/test_app.py",
        "redaction": {
            "local_only": True,
            "redactions": {
                "github_token": 1,
                "email": 2,
            },
        },
    }

    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"
    outputs = helper.action_outputs(result, Path("ci-result.json"), Path("ci-report.md"))

    assert outputs["redacted-categories"] == "2"

    helper.write_github_outputs(outputs, output_path)
    assert "redacted-categories=2\n" in output_path.read_text(encoding="utf-8")

    helper.append_step_summary(result, Path("ci-report.md"), summary_path)
    assert "- Redacted categories: `2`" in summary_path.read_text(encoding="utf-8")


def test_ci_triage_action_sample_matches_dependency_fixture(tmp_path: Path) -> None:
    generated_result = tmp_path / "ci-result.json"
    generated_report = tmp_path / "ci-report.md"
    generated_summary = tmp_path / "step-summary.md"

    assert (
        main(
            [
                "ci",
                "classify",
                "--log",
                str(FIXTURE),
                "--format",
                "json",
                "--out",
                str(generated_result),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "ci",
                "explain",
                "--log",
                str(FIXTURE),
                "--format",
                "markdown",
                "--out",
                str(generated_report),
            ]
        )
        == 0
    )

    sample_result = ACTION_SAMPLE / "ci-result.json"
    sample_report = ACTION_SAMPLE / "ci-report.md"
    sample_output = ACTION_SAMPLE / "github-output.txt"
    sample_summary = ACTION_SAMPLE / "step-summary.md"

    assert sample_result.read_text(encoding="utf-8") == generated_result.read_text(encoding="utf-8")
    assert sample_report.read_text(encoding="utf-8") == generated_report.read_text(encoding="utf-8")

    helper = _load_helper()
    result = json.loads(sample_result.read_text(encoding="utf-8"))
    expected_outputs = helper.action_outputs(
        result,
        Path("examples/ci-triage-action/sample/ci-result.json"),
        Path("examples/ci-triage-action/sample/ci-report.md"),
    )
    assert sample_output.read_text(encoding="utf-8") == "".join(
        f"{name}={value}\n" for name, value in expected_outputs.items()
    )

    helper.append_step_summary(
        result,
        Path("examples/ci-triage-action/sample/ci-report.md"),
        generated_summary,
    )
    assert sample_summary.read_text(encoding="utf-8") == generated_summary.read_text(
        encoding="utf-8"
    )
