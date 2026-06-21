from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from patchrail.cli import main


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "actions" / "ci-triage" / "action.yml"
HELPER = ROOT / "actions" / "ci-triage" / "scripts" / "ci_triage_action_outputs.py"
FIXTURE = ROOT / "examples" / "ci-triage" / "dependency-failure.log"


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
    assert "guide-url:" in text
    assert "pack-url:" in text
    assert "action-url:" in text


def test_ci_triage_action_helper_exports_reusable_outputs(tmp_path: Path) -> None:
    result_path = tmp_path / "ci-result.json"
    report_path = tmp_path / "ci-report.md"
    output_path = tmp_path / "github-output.txt"

    assert main(
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
    ) == 0
    assert main(
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
    ) == 0

    helper = _load_helper()
    assert helper.main(
        ["--result", str(result_path), "--report", str(report_path), "--output", str(output_path)]
    ) == 0

    lines = output_path.read_text(encoding="utf-8").splitlines()
    outputs = dict(line.split("=", 1) for line in lines)
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert outputs["failure-class"] == result["failure_class"]
    assert outputs["confidence"] == str(result["confidence"])
    assert outputs["guide-url"].startswith("https://getpatchrail.com/fix")
    assert outputs["pack-url"].startswith("https://patchrail.gumroad.com/l/ci-failure-triage")
    assert outputs["action-url"].startswith("https://github.com/patchrail/ci-triage-action")
    assert outputs["json-result"] == str(result_path)
    assert outputs["markdown-report"] == str(report_path)
