from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from patchrail import __version__
from patchrail.ci import classify_ci_log, redact_ci_log
from patchrail.funded_issues import explain_issue, load_funded_issues, summarize_issues
from patchrail.queue import (
    DEFAULT_DB_PATH,
    add_work_item,
    approve_work_item,
    export_audit_log,
    get_work_item,
    init_queue,
    list_work_items,
    reject_work_item,
)


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


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _load_schema(name: str) -> str:
    schema_files = {
        "ci-result": "ci-result.v1.schema.json",
        "work-item": "work-item.v1.schema.json",
    }
    if name not in schema_files:
        raise ValueError(f"unknown schema: {name}")
    return files("patchrail.schemas").joinpath(schema_files[name]).read_text(encoding="utf-8")


def _doctor_payload(root: Path) -> dict[str, Any]:
    fixture_root = root / "examples" / "ci-triage"
    fixtures = sorted(fixture_root.glob("*.log")) if fixture_root.exists() else []
    schema_available = bool(_load_schema("ci-result").strip())
    return {
        "schema_version": "patchrail.doctor.v1",
        "patchrail_version": __version__,
        "python_version": sys.version.split()[0],
        "project_root": str(root),
        "local_first": True,
        "requirements": {
            "billing_required": False,
            "external_model_required": False,
            "network_required": False,
            "github_write_permission_required": False,
        },
        "checks": {
            "ci_result_schema_available": schema_available,
            "ci_fixture_count": len(fixtures),
            "ci_fixture_directory": str(fixture_root),
        },
        "status": "ok" if schema_available else "warning",
    }


def _render_doctor_text(result: dict[str, Any]) -> str:
    requirements = result["requirements"]
    checks = result["checks"]
    lines = [
        f"PatchRail: {result['patchrail_version']}",
        f"Python: {result['python_version']}",
        f"Status: {result['status']}",
        f"Local-first: {result['local_first']}",
        f"CI fixtures: {checks['ci_fixture_count']}",
        f"Schema available: {checks['ci_result_schema_available']}",
        f"Network required: {requirements['network_required']}",
        f"External model required: {requirements['external_model_required']}",
        f"GitHub write permission required: {requirements['github_write_permission_required']}",
    ]
    return "\n".join(lines) + "\n"


def _render_doctor_markdown(result: dict[str, Any]) -> str:
    requirements = result["requirements"]
    checks = result["checks"]
    lines = [
        "# PatchRail Doctor",
        "",
        f"- PatchRail version: `{result['patchrail_version']}`",
        f"- Python version: `{result['python_version']}`",
        f"- Status: `{result['status']}`",
        f"- Local-first: `{result['local_first']}`",
        f"- CI fixtures: `{checks['ci_fixture_count']}`",
        f"- CI result schema available: `{checks['ci_result_schema_available']}`",
        "",
        "## Requirements",
        "",
        f"- Billing required: `{requirements['billing_required']}`",
        f"- External model required: `{requirements['external_model_required']}`",
        f"- Network required: `{requirements['network_required']}`",
        f"- GitHub write permission required: `{requirements['github_write_permission_required']}`",
    ]
    return "\n".join(lines) + "\n"


def _doctor(args: argparse.Namespace) -> int:
    result = _doctor_payload(Path.cwd())
    if args.format == "json":
        text = _json_dump(result)
    elif args.format == "markdown":
        text = _render_doctor_markdown(result)
    else:
        text = _render_doctor_text(result)
    _write_or_print(text, args.out)
    return 0 if result["status"] == "ok" else 1


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


def _render_funded_issues_text(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "No funded issues matched the safe read-only filters.\n"
    lines = []
    for issue in issues:
        lines.append(
            f"{issue['reference']} [{issue['risk_level']}] "
            f"{issue['funding']['display']} {issue['title']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# PatchRail Funded Issues",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Safe-only filter: `{payload['safe_only']}`",
        f"- Loaded: `{payload['total_loaded']}`",
        f"- Returned: `{payload['total_returned']}`",
        "",
        "## Issues",
        "",
    ]
    if not payload["issues"]:
        lines.append("No funded issues matched the safe read-only filters.")
    for issue in payload["issues"]:
        lines.extend(
            [
                f"### {issue['reference']}",
                "",
                f"- Title: {issue['title']}",
                f"- Platform: `{issue['platform']}`",
                f"- Funding: `{issue['funding']['display']}`",
                f"- Risk level: `{issue['risk_level']}`",
                f"- URL: {issue['url']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            (
                "PatchRail reads local metadata only. This command does not claim rewards, "
                "post comments, open pull requests, contact maintainers, or rank work by money alone."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _render_funded_issue_explain_markdown(payload: dict[str, Any]) -> str:
    issue = payload["issue"]
    lines = [
        "# PatchRail Funded Issue",
        "",
        f"- Reference: `{issue['reference']}`",
        f"- Title: {issue['title']}",
        f"- Platform: `{issue['platform']}`",
        f"- Funding: `{issue['funding']['display']}`",
        f"- Risk level: `{issue['risk_level']}`",
        f"- Read-only: `{payload['read_only']}`",
        f"- URL: {issue['url']}",
        "",
        "## Recommendation",
        "",
        payload["recommendation"],
        "",
        "## Signals",
        "",
    ]
    signals = issue["contribution_signals"]
    if signals:
        lines.extend(f"- {signal}" for signal in signals)
    else:
        lines.append("- No positive contribution-readiness signals recorded.")
    lines.extend(["", "## Risk Flags", ""])
    risk_flags = issue["risk_flags"]
    if risk_flags:
        lines.extend(f"- `{flag}`" for flag in risk_flags)
    else:
        lines.append("- No high-risk flags recorded.")
    lines.extend(["", "## Blocked Actions", ""])
    lines.extend(f"- `{action}`" for action in payload["ethics"]["blocked"])
    lines.extend(
        [
            "",
            "PatchRail does not claim rewards, post comments, open pull requests, "
            "or contact maintainers from funded issue commands.",
        ]
    )
    return "\n".join(lines) + "\n"


def _default_funded_issues_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "issues.json"


def _load_funded_issues_for_cli(source: Path) -> list[Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    return load_funded_issues(source)


def _funded_issues_list(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        payload = summarize_issues(
            issues,
            safe_only=not args.include_risky,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_markdown(payload)
    else:
        text = _render_funded_issues_text(payload["issues"])
    _write_or_print(text, args.out)
    return 0


def _funded_issues_explain(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        payload = explain_issue(issues, args.reference)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    except KeyError:
        print(f"Unknown funded issue: {args.reference}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issue_explain_markdown(payload)
    else:
        text = _render_funded_issues_text([payload["issue"]])
    _write_or_print(text, args.out)
    return 0


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


def _read_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_json and args.payload_file:
        raise ValueError("use --payload-json or --payload-file, not both")
    if args.payload_file:
        return json.loads(args.payload_file.read_text(encoding="utf-8"))
    if args.payload_json:
        return json.loads(args.payload_json)
    return {}


def _render_queue_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No work items.\n"
    lines = []
    for item in items:
        lines.append(
            f"#{item['id']} {item['status']} priority={item['priority']} "
            f"{item['kind']}: {item['title']}"
        )
    return "\n".join(lines) + "\n"


def _queue_init(args: argparse.Namespace) -> int:
    payload = init_queue(args.db)
    _write_or_print(json.dumps(payload, indent=2, sort_keys=True) + "\n", args.out)
    return 0


def _queue_add(args: argparse.Namespace) -> int:
    item = add_work_item(
        db_path=args.db,
        kind=args.kind,
        title=args.title,
        source=args.source,
        priority=args.priority,
        payload=_read_payload(args),
    )
    _write_or_print(json.dumps(item, indent=2, sort_keys=True) + "\n", args.out)
    return 0


def _queue_list(args: argparse.Namespace) -> int:
    items = list_work_items(db_path=args.db, status=args.status)
    if args.format == "json":
        text = json.dumps(items, indent=2, sort_keys=True) + "\n"
    else:
        text = _render_queue_text(items)
    _write_or_print(text, args.out)
    return 0


def _queue_show(args: argparse.Namespace) -> int:
    item = get_work_item(args.id, db_path=args.db)
    _write_or_print(json.dumps(item, indent=2, sort_keys=True) + "\n", args.out)
    return 0


def _queue_approve(args: argparse.Namespace) -> int:
    item = approve_work_item(args.id, db_path=args.db, note=args.note)
    _write_or_print(json.dumps(item, indent=2, sort_keys=True) + "\n", args.out)
    return 0


def _queue_reject(args: argparse.Namespace) -> int:
    item = reject_work_item(args.id, db_path=args.db, note=args.note)
    _write_or_print(json.dumps(item, indent=2, sort_keys=True) + "\n", args.out)
    return 0


def _queue_export(args: argparse.Namespace) -> int:
    events = export_audit_log(db_path=args.db)
    if args.format == "json":
        text = json.dumps(events, indent=2, sort_keys=True) + "\n"
    else:
        text = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    _write_or_print(text, args.out)
    return 0


def _add_queue_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite queue path. Defaults to .patchrail/queue.sqlite in the current directory.",
    )
    parser.add_argument("--out", type=Path, help="Optional output path.")


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
        choices=["ci-result", "work-item"],
        help="Schema name to emit.",
    )
    schema.add_argument("--out", type=Path, help="Optional output path.")
    schema.set_defaults(func=_schema)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check local PatchRail installation and safety requirements.",
    )
    doctor.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="text",
        help="Output format.",
    )
    doctor.add_argument("--out", type=Path, help="Optional output path.")
    doctor.set_defaults(func=_doctor)

    queue_parser = subparsers.add_parser(
        "queue",
        help="Manage local human-approved maintainer work items.",
    )
    queue_subparsers = queue_parser.add_subparsers(dest="queue_command", required=True)

    queue_init = queue_subparsers.add_parser("init", help="Initialize a local SQLite queue.")
    _add_queue_db_argument(queue_init)
    queue_init.set_defaults(func=_queue_init)

    queue_add = queue_subparsers.add_parser("add", help="Add a proposed work item.")
    _add_queue_db_argument(queue_add)
    queue_add.add_argument("--kind", required=True, help="Work item kind, e.g. ci_failure.")
    queue_add.add_argument("--title", required=True, help="Human-readable work item title.")
    queue_add.add_argument("--source", help="Optional source such as a repo, URL, or CI run.")
    queue_add.add_argument("--priority", type=int, default=0, help="Higher numbers sort first.")
    queue_add.add_argument("--payload-json", help="Optional structured JSON payload.")
    queue_add.add_argument("--payload-file", type=Path, help="Optional JSON payload file.")
    queue_add.set_defaults(func=_queue_add)

    queue_list = queue_subparsers.add_parser("list", help="List work items.")
    _add_queue_db_argument(queue_list)
    queue_list.add_argument(
        "--status",
        choices=["proposed", "approved", "rejected", "done"],
        help="Filter by status.",
    )
    queue_list.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    queue_list.set_defaults(func=_queue_list)

    queue_show = queue_subparsers.add_parser("show", help="Show one work item as JSON.")
    _add_queue_db_argument(queue_show)
    queue_show.add_argument("id", type=int, help="Work item id.")
    queue_show.set_defaults(func=_queue_show)

    queue_approve = queue_subparsers.add_parser("approve", help="Approve a proposed work item.")
    _add_queue_db_argument(queue_approve)
    queue_approve.add_argument("id", type=int, help="Work item id.")
    queue_approve.add_argument("--note", help="Decision note.")
    queue_approve.set_defaults(func=_queue_approve)

    queue_reject = queue_subparsers.add_parser("reject", help="Reject a work item.")
    _add_queue_db_argument(queue_reject)
    queue_reject.add_argument("id", type=int, help="Work item id.")
    queue_reject.add_argument("--note", help="Decision note.")
    queue_reject.set_defaults(func=_queue_reject)

    queue_export = queue_subparsers.add_parser("export", help="Export audit events.")
    _add_queue_db_argument(queue_export)
    queue_export.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        help="Output format.",
    )
    queue_export.set_defaults(func=_queue_export)

    funded = subparsers.add_parser(
        "funded-issues",
        help="Inspect funded maintenance issues from local read-only metadata.",
    )
    funded_subparsers = funded.add_subparsers(dest="funded_issues_command", required=True)

    funded_list = funded_subparsers.add_parser(
        "list",
        help="List local funded issue metadata with safe-only filtering by default.",
    )
    funded_list.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_list.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_list.add_argument("--platform", help="Filter by funding platform.")
    funded_list.add_argument("--language", help="Filter by repository language.")
    funded_list.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_list.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="text",
        help="Output format.",
    )
    funded_list.add_argument("--out", type=Path, help="Optional output path.")
    funded_list.set_defaults(func=_funded_issues_list)

    funded_explain = funded_subparsers.add_parser(
        "explain",
        help="Explain one local funded issue record and its anti-abuse boundary.",
    )
    funded_explain.add_argument("reference", help="Issue id, URL, or owner/repo#number.")
    funded_explain.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_explain.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_explain.add_argument("--out", type=Path, help="Optional output path.")
    funded_explain.set_defaults(func=_funded_issues_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
