from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


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


def failure_slug(result: dict[str, Any]) -> str:
    failure_class = str(result.get("failure_class") or "unknown").strip() or "unknown"
    return failure_class.replace("_", "-")


def attribution_value(result: dict[str, Any], key: str, default: str) -> str:
    for field in ("pack_url", "guide_url", "action_url"):
        url = str(result.get(field) or "")
        if not url:
            continue
        values = parse_qs(urlparse(url).query).get(key)
        if values and values[0]:
            return values[0]
    return default


def adoption_key(result: dict[str, Any], slug: str) -> str:
    source = attribution_value(result, "utm_source", "cli")
    campaign = attribution_value(result, "utm_campaign", slug)
    return f"ci-triage:{source}:{campaign}:{slug}"


def adoption_event(
    result: dict[str, Any],
    slug: str,
    result_path: Path | None = None,
    report_path: Path | None = None,
    action_ref: str = "local",
    action_repository: str = "patchrail/ci-triage-action",
) -> str:
    source = attribution_value(result, "utm_source", "cli")
    campaign = attribution_value(result, "utm_campaign", slug)
    event = {
        "schema_version": "patchrail.ci_triage_adoption_event.v1",
        "product": "ci-triage-action",
        "action_ref": action_ref or "local",
        "action_repository": action_repository or "patchrail/ci-triage-action",
        "adoption_key": f"ci-triage:{source}:{campaign}:{slug}",
        "failure_class": str(result.get("failure_class") or "unknown"),
        "failure_slug": slug,
        "utm_source": source,
        "utm_campaign": campaign,
        "confidence": str(result.get("confidence") or "0"),
        "redacted_categories": redacted_category_count(result),
        "artifact_name": f"patchrail-ci-triage-{slug}",
    }
    if result_path is not None:
        event["json_result"] = str(result_path)
    if report_path is not None:
        event["markdown_report"] = str(report_path)
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def action_outputs(
    result: dict[str, Any],
    result_path: Path,
    report_path: Path,
    action_ref: str = "local",
    action_repository: str = "patchrail/ci-triage-action",
) -> dict[str, str]:
    slug = failure_slug(result)
    outputs = {}
    for output_name, result_name in OUTPUT_KEYS.items():
        outputs[output_name] = str(result.get(result_name, ""))
        if output_name == "failure-class":
            outputs["failure-slug"] = slug
            outputs["utm-source"] = attribution_value(result, "utm_source", "cli")
            outputs["utm-campaign"] = attribution_value(result, "utm_campaign", slug)
    outputs["artifact-name"] = f"patchrail-ci-triage-{slug}"
    outputs["json-result"] = str(result_path)
    outputs["markdown-report"] = str(report_path)
    outputs["summary-line"] = summary_line(result)
    outputs["redacted-categories"] = str(redacted_category_count(result))
    outputs["adoption-key"] = adoption_key(result, slug)
    outputs["adoption-event-json"] = adoption_event(
        result,
        slug,
        result_path=result_path,
        report_path=report_path,
        action_ref=action_ref,
        action_repository=action_repository,
    )
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
        f"- Adoption key: `{adoption_key(result, failure_slug(result))}`",
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
    write_github_outputs(
        action_outputs(
            result,
            args.result,
            args.report,
            action_ref=os.environ.get("GITHUB_ACTION_REF", "local"),
            action_repository=os.environ.get(
                "GITHUB_ACTION_REPOSITORY",
                "patchrail/ci-triage-action",
            ),
        ),
        args.output,
    )
    if args.summary is not None:
        append_step_summary(result, args.report, args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
