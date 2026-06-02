from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from patchrail.ci import classify_ci_log, redact_ci_log


def _read_log(path: Path | None) -> str:
    if path is None:
        return sys.stdin.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _render_text(result: dict[str, Any]) -> str:
    lines = [
        f"Root cause: {result['failure_class']}",
        f"Confidence: {result['confidence']}",
        f"Subsystem: {result['likely_subsystem']}",
        f"Reproduce: {result['reproduction_command']}",
        f"Suggested action: {result['minimal_repair_strategy']}",
    ]
    redaction = result.get("redaction")
    if isinstance(redaction, dict):
        redactions = redaction.get("redactions") or {}
        lines.append(f"Redaction: {len(redactions)} categories redacted locally")
    return "\n".join(lines) + "\n"


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# PatchRail CI Report",
        "",
        f"- Root cause: `{result['failure_class']}`",
        f"- Confidence: `{result['confidence']}`",
        f"- Subsystem: {result['likely_subsystem']}",
        f"- Reproduce: `{result['reproduction_command']}`",
        f"- Suggested action: {result['minimal_repair_strategy']}",
        "",
        "## Evidence signals",
        "",
    ]
    signals = list(result.get("signals") or [])
    if signals:
        lines.extend(f"- `{signal}`" for signal in signals)
    else:
        lines.append("- No high-confidence local signal found.")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            (
                "PatchRail classified this log locally. It did not create a pull request, "
                "post a comment, claim funding, or send data to an external service."
            ),
        ]
    )
    redaction = result.get("redaction")
    if isinstance(redaction, dict):
        redactions = redaction.get("redactions") or {}
        lines.extend(
            [
                "",
                "## Redaction",
                "",
                f"- Local redaction enabled: `{bool(redaction.get('local_only'))}`",
                f"- Categories redacted: `{len(redactions)}`",
            ]
        )
        for name, count in sorted(redactions.items()):
            lines.append(f"- `{name}`: `{count}`")
    return "\n".join(lines) + "\n"


def _format_result(result: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output_format == "markdown":
        return _render_markdown(result)
    return _render_text(result)


def _write_or_print(text: str, out: Path | None) -> None:
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")


def _load_schema(name: str) -> str:
    if name != "ci-result":
        raise ValueError(f"unknown schema: {name}")
    return (
        files("patchrail.schemas").joinpath("ci-result.v1.schema.json").read_text(encoding="utf-8")
    )


def _ci_explain(args: argparse.Namespace) -> int:
    raw_log = _read_log(args.log)
    result = classify_ci_log(raw_log)
    if args.redact:
        redaction = redact_ci_log(raw_log)
        result["redaction"] = {
            "redacted": redaction["text"],
            "redactions": redaction["redactions"],
            "local_only": True,
        }
    _write_or_print(_format_result(result, args.format), args.out)
    return 0


def _redact(args: argparse.Namespace) -> int:
    redaction = redact_ci_log(_read_log(args.log))
    if args.format == "json":
        text = json.dumps(redaction, indent=2, sort_keys=True) + "\n"
    else:
        text = str(redaction["text"])
        if not text.endswith("\n"):
            text += "\n"
    _write_or_print(text, args.out)
    return 0


def _schema(args: argparse.Namespace) -> int:
    text = _load_schema(args.schema)
    if not text.endswith("\n"):
        text += "\n"
    _write_or_print(text, args.out)
    return 0


def _expected_path_for(log_path: Path) -> Path:
    return log_path.with_suffix(".expected.json")


def _load_expected(log_path: Path) -> dict[str, Any]:
    expected_path = _expected_path_for(log_path)
    if not expected_path.exists():
        return {
            "failure_class": None,
            "minimum_confidence": None,
            "_missing_expected_file": str(expected_path),
        }
    return json.loads(expected_path.read_text(encoding="utf-8"))


def _benchmark_case(root: Path, log_path: Path) -> dict[str, Any]:
    expected = _load_expected(log_path)
    result = classify_ci_log(log_path.read_text(encoding="utf-8", errors="replace"))
    mismatches: list[str] = []

    expected_class = expected.get("failure_class")
    if expected_class is None:
        mismatches.append("missing expected failure_class")
    elif result["failure_class"] != expected_class:
        mismatches.append(
            f"failure_class expected {expected_class!r}, got {result['failure_class']!r}"
        )

    minimum_confidence = expected.get("minimum_confidence")
    if minimum_confidence is not None and result["confidence"] < float(minimum_confidence):
        mismatches.append(
            f"confidence expected >= {minimum_confidence}, got {result['confidence']}"
        )

    return {
        "log": str(log_path.relative_to(root)),
        "expected_failure_class": expected_class,
        "actual_failure_class": result["failure_class"],
        "expected_minimum_confidence": minimum_confidence,
        "actual_confidence": result["confidence"],
        "passed": not mismatches,
        "mismatches": mismatches,
    }


def _run_ci_benchmark(path: Path) -> dict[str, Any]:
    root = path.resolve()
    if root.is_file():
        log_paths = [root]
        root = root.parent
    else:
        log_paths = sorted(root.rglob("*.log"))

    cases = [_benchmark_case(root, log_path) for log_path in log_paths]
    passed = sum(1 for case in cases if case["passed"])
    failed = len(cases) - passed
    return {
        "schema_version": "patchrail.ci_benchmark.v1",
        "root": str(root),
        "total_cases": len(cases),
        "passed": passed,
        "failed": failed,
        "cases": cases,
        "requirements": {
            "billing_required": False,
            "external_model_required": False,
            "network_required": False,
        },
    }


def _render_benchmark_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# PatchRail CI Benchmark",
        "",
        f"- Total cases: `{result['total_cases']}`",
        f"- Passed: `{result['passed']}`",
        f"- Failed: `{result['failed']}`",
        "",
        "## Cases",
        "",
    ]
    for case in result["cases"]:
        status = "pass" if case["passed"] else "fail"
        lines.append(
            f"- `{status}` `{case['log']}`: expected "
            f"`{case['expected_failure_class']}`, got `{case['actual_failure_class']}`"
        )
        for mismatch in case["mismatches"]:
            lines.append(f"  - {mismatch}")
    return "\n".join(lines) + "\n"


def _render_benchmark_text(result: dict[str, Any]) -> str:
    lines = [
        f"Total cases: {result['total_cases']}",
        f"Passed: {result['passed']}",
        f"Failed: {result['failed']}",
    ]
    for case in result["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        lines.append(f"{status} {case['log']}: {case['actual_failure_class']}")
    return "\n".join(lines) + "\n"


def _ci_benchmark(args: argparse.Namespace) -> int:
    result = _run_ci_benchmark(args.path)
    if args.format == "json":
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    elif args.format == "markdown":
        text = _render_benchmark_markdown(result)
    else:
        text = _render_benchmark_text(result)
    _write_or_print(text, args.out)
    return 0 if result["failed"] == 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patchrail",
        description="Local-first maintainer automation for open-source projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ci_parser = subparsers.add_parser("ci", help="Classify and explain CI failures locally.")
    ci_subparsers = ci_parser.add_subparsers(dest="ci_command", required=True)

    explain = ci_subparsers.add_parser("explain", help="Explain a failed CI log.")
    explain.add_argument("--log", type=Path, help="CI log file. Reads stdin when omitted.")
    explain.add_argument(
        "--redact",
        action="store_true",
        help="Include local redaction metadata for secrets, emails and home paths.",
    )
    explain.add_argument(
        "--format",
        choices=["markdown", "json", "text"],
        default="markdown",
        help="Output format.",
    )
    explain.add_argument("--out", type=Path, help="Optional output path.")
    explain.set_defaults(func=_ci_explain)

    classify = ci_subparsers.add_parser("classify", help="Emit machine-readable CI classification.")
    classify.add_argument("--log", type=Path, help="CI log file. Reads stdin when omitted.")
    classify.add_argument(
        "--redact",
        action="store_true",
        help="Include local redaction metadata for secrets, emails and home paths.",
    )
    classify.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="json",
        help="Output format.",
    )
    classify.add_argument("--out", type=Path, help="Optional output path.")
    classify.set_defaults(func=_ci_explain)

    benchmark = ci_subparsers.add_parser(
        "benchmark",
        help="Run local fixture expectations against CI classifier output.",
    )
    benchmark.add_argument("path", type=Path, help="Directory or single .log file to benchmark.")
    benchmark.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="json",
        help="Output format.",
    )
    benchmark.add_argument("--out", type=Path, help="Optional output path.")
    benchmark.set_defaults(func=_ci_benchmark)

    redact = subparsers.add_parser("redact", help="Redact secrets, emails and home paths locally.")
    redact.add_argument("--log", type=Path, help="CI log file. Reads stdin when omitted.")
    redact.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format.",
    )
    redact.add_argument("--out", type=Path, help="Optional output path.")
    redact.set_defaults(func=_redact)

    schema = subparsers.add_parser("schema", help="Print PatchRail's versioned JSON schemas.")
    schema.add_argument(
        "schema",
        choices=["ci-result"],
        help="Schema name to emit.",
    )
    schema.add_argument("--out", type=Path, help="Optional output path.")
    schema.set_defaults(func=_schema)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
