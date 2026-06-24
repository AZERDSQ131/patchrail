from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


OUTPUT_KEYS = {
    "failure-class": "failure_class",
    "confidence": "confidence",
    "guide-url": "guide_url",
    "pack-url": "pack_url",
    "action-url": "action_url",
    "next-step": "minimal_repair_strategy",
    "reproduction-command": "reproduction_command",
}


def summary_line(result: dict[str, Any]) -> str:
    failure_class = str(result.get("failure_class") or "unknown")
    confidence = str(result.get("confidence") or "0")
    guide_url = str(result.get("guide_url") or "")
    return f"PatchRail CI triage: {failure_class} ({confidence}) -> {guide_url}"


def redacted_category_count(result: dict[str, Any]) -> int:
    redaction = result.get("redaction")
    if not isinstance(redaction, dict):
        return 0
    redactions = redaction.get("redactions")
    if not isinstance(redactions, dict):
        return 0
    return len(redactions)


def action_outputs(result: dict[str, Any], result_path: Path, report_path: Path) -> dict[str, str]:
    outputs = {
        output_name: str(result.get(result_name, ""))
        for output_name, result_name in OUTPUT_KEYS.items()
    }
    outputs["json-result"] = str(result_path)
    outputs["markdown-report"] = str(report_path)
    outputs["summary-line"] = summary_line(result)
    outputs["redacted-categories"] = str(redacted_category_count(result))
    return outputs


def write_github_outputs(outputs: dict[str, str], path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            clean_value = value.replace("\n", " ").replace("\r", " ")
            handle.write(f"{name}={clean_value}\n")


def append_step_summary(result: dict[str, Any], report_path: Path, path: Path) -> None:
    lines = [
        "## PatchRail CI triage",
        "",
        f"- Summary: {summary_line(result)}",
        f"- Next step: {result.get('minimal_repair_strategy') or 'Open the report for repair details.'}",
        f"- Redacted categories: `{redacted_category_count(result)}`",
        f"- Report: `{report_path}`",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export PatchRail CI triage GitHub outputs.")
    parser.add_argument("--result", type=Path, required=True, help="PatchRail ci-result.json path.")
    parser.add_argument("--report", type=Path, required=True, help="PatchRail ci-report.md path.")
    parser.add_argument("--output", type=Path, required=True, help="GitHub output file path.")
    parser.add_argument("--summary", type=Path, help="Optional GitHub step summary path.")
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    write_github_outputs(action_outputs(result, args.result, args.report), args.output)
    if args.summary is not None:
        append_step_summary(result, args.report, args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
