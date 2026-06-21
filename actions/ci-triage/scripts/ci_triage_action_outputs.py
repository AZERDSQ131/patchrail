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
}


def action_outputs(result: dict[str, Any], result_path: Path, report_path: Path) -> dict[str, str]:
    outputs = {
        output_name: str(result.get(result_name, ""))
        for output_name, result_name in OUTPUT_KEYS.items()
    }
    outputs["json-result"] = str(result_path)
    outputs["markdown-report"] = str(report_path)
    return outputs


def write_github_outputs(outputs: dict[str, str], path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            clean_value = value.replace("\n", " ").replace("\r", " ")
            handle.write(f"{name}={clean_value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export PatchRail CI triage GitHub outputs.")
    parser.add_argument("--result", type=Path, required=True, help="PatchRail ci-result.json path.")
    parser.add_argument("--report", type=Path, required=True, help="PatchRail ci-report.md path.")
    parser.add_argument("--output", type=Path, required=True, help="GitHub output file path.")
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    write_github_outputs(action_outputs(result, args.result, args.report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
