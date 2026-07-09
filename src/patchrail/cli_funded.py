from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from patchrail.cli import _json_dump, _write_or_print
from patchrail.funded_issues import (
    SUPPORTED_PROVIDERS,
    VALID_OPPORTUNITY_STATES,
    VALID_RISK_LEVELS,
    apply_recheck_to_store,
    assess_competition_batch,
    assess_payout_effort_batch,
    assess_staleness_batch,
    assess_testability_batch,
    board_issue_records,
    board_payload,
    cash_actions_funded_issues,
    client_report_funded_issues,
    empty_store,
    explain_issue,
    fresh_issues,
    fulfillment_packet_funded_issues,
    import_provider_export,
    load_client_profile,
    load_funded_issues,
    load_store,
    merge_into_store,
    parse_board_html,
    purge_blocklisted_entries,
    recheck_funded_issues,
    report_funded_issues,
    save_store,
    score_funded_issues,
    shortlist_funded_issues,
    store_status,
    summarize_issues,
    validate_funded_issues,
)


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


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, list):
        text = "; ".join(str(item) for item in value)
    else:
        text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def _render_funded_issues_csv(issues: list[dict[str, Any]]) -> str:
    fieldnames = [
        "platform",
        "repository",
        "reference",
        "issue_number",
        "title",
        "url",
        "funding_amount",
        "funding_currency",
        "funding_display",
        "language",
        "opportunity_state",
        "risk_level",
        "safe_to_list",
        "contribution_signals",
        "risk_flags",
        "contribution_guidelines_url",
        "read_only",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for issue in issues:
        funding = issue["funding"]
        writer.writerow(
            {
                "platform": _csv_cell(issue["platform"]),
                "repository": _csv_cell(issue["repository"]),
                "reference": _csv_cell(issue["reference"]),
                "issue_number": _csv_cell(issue["issue_number"]),
                "title": _csv_cell(issue["title"]),
                "url": _csv_cell(issue["url"]),
                "funding_amount": _csv_cell(funding["amount"]),
                "funding_currency": _csv_cell(funding["currency"]),
                "funding_display": _csv_cell(funding["display"]),
                "language": _csv_cell(issue["language"]),
                "opportunity_state": _csv_cell(issue["opportunity_state"]),
                "risk_level": _csv_cell(issue["risk_level"]),
                "safe_to_list": _csv_cell(issue["safe_to_list"]),
                "contribution_signals": _csv_cell(issue["contribution_signals"]),
                "risk_flags": _csv_cell(issue["risk_flags"]),
                "contribution_guidelines_url": _csv_cell(issue["contribution_guidelines_url"]),
                "read_only": _csv_cell(issue["read_only"]),
            }
        )
    return buffer.getvalue()


def _render_funded_issues_jsonl(issues: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(issue, sort_keys=True) + "\n" for issue in issues)


def _funded_issues_invalid_validation_payload(source: Path, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": "patchrail.funded_issues.validation.v1",
        "source_schema_version": None,
        "status": "invalid",
        "read_only": True,
        "source": str(source),
        "total_loaded": 0,
        "warning_count": 0,
        "errors": [str(exc)],
        "warnings": {
            "duplicate_ids": [],
            "duplicate_references": [],
            "missing_funding": [],
            "missing_contribution_guidelines": [],
            "missing_contribution_signals": [],
            "high_risk": [],
            "stale_or_closed": [],
        },
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": "Validation is local and read-only. Invalid sources are not usable evidence.",
    }


def _render_funded_issues_validate_text(payload: dict[str, Any]) -> str:
    lines = [
        "PatchRail Funded Issues Validation",
        f"Status: {payload['status']}",
        f"Loaded: {payload['total_loaded']}",
        f"Warnings: {payload['warning_count']}",
        "Read-only: True",
    ]
    errors = payload.get("errors") or []
    for error in errors:
        lines.append(f"ERROR {error}")
    for warning_name, values in payload["warnings"].items():
        if values:
            lines.append(f"WARN {warning_name}: {', '.join(values)}")
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
                f"- Opportunity state: `{issue['opportunity_state']}`",
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
        f"- Opportunity state: `{issue['opportunity_state']}`",
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
    lines.extend(
        [
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["ethics"]["blocked"])
    lines.extend(
        [
            "",
            "PatchRail does not claim rewards, post comments, open pull requests, "
            "or contact maintainers from funded issue commands.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_funded_issues_import_markdown(payload: dict[str, Any]) -> str:
    source = payload["import_source"]
    lines = [
        "# PatchRail Funded Issue Import",
        "",
        f"- Provider: `{source['provider']}`",
        f"- Local file only: `{source['local_file_only']}`",
        f"- Records loaded: `{source['records_loaded']}`",
        f"- Read-only: `{payload['read_only']}`",
        f"- Issues exported: `{len(payload['issues'])}`",
        "",
        "## Issues",
        "",
    ]
    if not payload["issues"]:
        lines.append("No issues were normalized from the provider export.")
    for issue in payload["issues"]:
        lines.extend(
            [
                f"### {issue['reference']}",
                "",
                f"- Title: {issue['title']}",
                f"- Funding: `{issue['funding']['display']}`",
                f"- Opportunity state: `{issue['opportunity_state']}`",
                f"- Risk level: `{issue['risk_level']}`",
                f"- Safe to list: `{issue['safe_to_list']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            (
                "This command normalizes a local provider export. It does not fetch APIs, "
                "scrape websites, claim rewards, post comments, open pull requests, or contact maintainers."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _render_funded_issues_report_text(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    moat = payload["no_go_moat"]
    decision = payload["decision_summary"]
    budget = payload["delivery_budget"]
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "PatchRail Funded Issues Report",
        f"Client profile: {profile_name}",
        f"Loaded: {totals['loaded']}",
        f"In scope: {totals['in_scope']}",
        f"Safe to list: {totals['safe_to_list']}",
        f"High risk: {totals['high_risk']}",
        f"Funding unknown: {totals['funding_unknown']}",
        (
            "No-go moat: "
            f"{moat['high_risk_or_excluded']} high-risk/excluded, "
            f"{moat['missing_contribution_guidelines']} missing guidelines"
        ),
        (
            "Decision summary: "
            f"{decision['candidate_rows']} candidates, "
            f"{decision['no_go_rows']} no-go rows, "
            f"{decision['verification_needed']} funding/state rechecks"
        ),
        f"Recommended batch action: {decision['recommended_batch_action']}",
        (
            "Delivery budget: "
            f"{budget['suggested_package']}, "
            f"{budget['estimated_review_minutes']} min local review, "
            f"within margin budget: {budget['within_margin_budget']}"
        ),
        _delivery_pack_summary(payload["delivery_pack"]),
        _source_quality_summary(payload["source_quality"]),
        _recheck_plan_summary(payload["recheck_plan"]),
        _evidence_debt_summary(payload["evidence_debt"]),
        _client_fit_summary_line(payload["client_fit_summary"]),
        f"Client fit gaps: {len(payload['client_fit_gaps'])}",
        _intake_followup_summary(payload["intake_followup"]),
        _cash_path_summary(payload["cash_path_status"]),
        _operator_next_steps_summary(payload["operator_next_steps"]),
        "Read-only: True",
    ]
    return "\n".join(lines) + "\n"


def _source_quality_summary(source_quality: dict[str, Any]) -> str:
    sources = source_quality["sources"]
    summary = source_quality["summary"]
    if not sources:
        return f"Source quality: no source rows matched the filters, status {summary['status']}"
    source, stats = sorted(
        sources.items(),
        key=lambda item: (
            -int(item[1]["candidate_rows"]),
            -float(item[1]["usable_signal_ratio"]),
            -float(item[1]["average_score"]),
            item[0],
        ),
    )[0]
    return (
        "Source quality: "
        f"{source} has {stats['candidate_rows']}/{stats['total_rows']} candidate rows, "
        f"{stats['usable_signal_ratio']} usable signal ratio, "
        f"status {summary['status']}"
    )


def _delivery_pack_summary(delivery_pack: dict[str, Any]) -> str:
    handoff = delivery_pack["handoff"]
    return (
        "Delivery pack: "
        f"{len(handoff['candidate_references'])} candidate refs, "
        f"{len(handoff['verification_references'])} verification refs, "
        f"{len(handoff['no_go_references'])} no-go refs"
    )


def _recheck_plan_summary(recheck_plan: dict[str, Any]) -> str:
    return (
        "Recheck plan: "
        f"{recheck_plan['recheck_rows']} active rechecks, "
        f"{recheck_plan['no_go_rows']} archived no-go rows"
    )


def _evidence_debt_summary(evidence_debt: dict[str, Any]) -> str:
    return (
        "Evidence debt: "
        f"{evidence_debt['blocking_rows']} blocking rows, "
        f"highest priority {evidence_debt['highest_priority']}, "
        f"next action {evidence_debt['next_action']}"
    )


def _client_fit_summary_line(client_fit_summary: dict[str, Any]) -> str:
    return (
        "Client fit summary: "
        f"{client_fit_summary['matching_rows']}/{client_fit_summary['total_rows']} "
        f"matching rows, {client_fit_summary['excluded_rows']} excluded, "
        f"status {client_fit_summary['status']}"
    )


def _intake_followup_summary(intake_followup: dict[str, Any]) -> str:
    return (
        "Intake follow-up: "
        f"{intake_followup['status']}, "
        f"{len(intake_followup['requested_fields'])} fields, "
        f"{intake_followup['required_before_paid_delivery']} required"
    )


def _cash_path_summary(cash_path_status: dict[str, Any]) -> str:
    return (
        "Funding path: "
        f"{cash_path_status['next_revenue_action']}, "
        f"handoff ready: {cash_path_status['buyer_ready']}, "
        f"outbound action allowed now: {cash_path_status['payment_route_allowed_now']}"
    )


def _operator_next_steps_summary(operator_next_steps: dict[str, Any]) -> str:
    return (
        "Operator next steps: "
        f"{operator_next_steps['primary_action']}, "
        f"{len(operator_next_steps['steps'])} steps, "
        f"external body allowed: {operator_next_steps['external_body_allowed']}, "
        f"outbound action allowed now: {operator_next_steps['payment_route_allowed_now']}"
    )


def _funded_issues_profile_name(filters: dict[str, Any]) -> str:
    profile = filters.get("profile")
    if not isinstance(profile, dict):
        return "none"
    name = profile.get("name")
    return str(name) if name else "unnamed"


def _append_source_quality_markdown(
    lines: list[str],
    source_quality: dict[str, Any],
) -> None:
    summary = source_quality["summary"]
    lines.extend(
        [
            "",
            "## Source Quality",
            "",
            f"- Status: `{summary['status']}`",
            f"- Sources: `{summary['source_count']}`",
            f"- Candidate sources: `{summary['candidate_source_count']}`",
            f"- No-go-only sources: `{summary['no_go_only_source_count']}`",
            f"- Next tracker action: {summary['next_tracker_action']}",
            "",
            "| Source | Rows | Candidates | No-go | Safe | Rechecks | Auth | Avg score | Usable signal | Recommended use |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    sources = source_quality["sources"]
    if sources:
        for source, stats in sources.items():
            lines.append(
                f"| `{source}` | {stats['total_rows']} | {stats['candidate_rows']} | "
                f"{stats['no_go_rows']} | {stats['safe_to_list']} | "
                f"{stats['funding_verification_needed']} | "
                f"{stats['authorization_needed']} | {stats['average_score']} | "
                f"{stats['usable_signal_ratio']} | {stats['recommended_use']} |"
            )
    else:
        lines.append("| n/a | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | No rows matched the filters. |")
    lines.extend(["", summary["boundary"], "", source_quality["boundary"]])


def _append_delivery_pack_markdown(
    lines: list[str],
    delivery_pack: dict[str, Any],
) -> None:
    handoff = delivery_pack["handoff"]
    lines.extend(
        [
            "",
            "## Delivery Pack",
            "",
            f"- Suggested package: `{delivery_pack['suggested_package']}`",
            "- Candidate references: " + _format_reference_list(handoff["candidate_references"]),
            "- Verification references: "
            + _format_reference_list(handoff["verification_references"]),
            "- No-go references: " + _format_reference_list(handoff["no_go_references"]),
            "",
            "| Phase | Rows | References | Objective | Exit criteria |",
            "|---|---:|---|---|---|",
        ]
    )
    for phase in delivery_pack["phases"]:
        lines.append(
            f"| `{phase['phase']}` | {phase['row_count']} | "
            f"{_format_reference_list(phase['references'])} | "
            f"{phase['objective']} | {phase['exit_criteria']} |"
        )
    lines.extend(["", delivery_pack["boundary"]])


def _format_reference_list(references: list[str]) -> str:
    if not references:
        return "`none`"
    return ", ".join(f"`{reference}`" for reference in references)


def _append_client_fit_summary_markdown(
    lines: list[str],
    client_fit_summary: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Client Fit Summary",
            "",
            f"- Profile: `{client_fit_summary['profile_name'] or 'none'}`",
            f"- Status: `{client_fit_summary['status']}`",
            f"- Matching rows: `{client_fit_summary['matching_rows']}` / "
            f"`{client_fit_summary['total_rows']}`",
            f"- Excluded rows: `{client_fit_summary['excluded_rows']}`",
            f"- Recommended action: {client_fit_summary['recommended_action']}",
            "",
            "| Gap code | Count |",
            "|---|---:|",
        ]
    )
    if client_fit_summary["gap_counts"]:
        for gap_code, count in client_fit_summary["gap_counts"].items():
            lines.append(f"| `{gap_code}` | {count} |")
    else:
        lines.append("| n/a | 0 |")
    lines.extend(["", client_fit_summary["boundary"]])


def _append_recheck_plan_markdown(
    lines: list[str],
    recheck_plan: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Recheck Plan",
            "",
            f"- Rows: `{recheck_plan['total_rows']}`",
            f"- Active rechecks: `{recheck_plan['recheck_rows']}`",
            f"- Archived no-go rows: `{recheck_plan['no_go_rows']}`",
            "",
            "| Priority | Count |",
            "|---|---:|",
        ]
    )
    if recheck_plan["priority_counts"]:
        for priority, count in recheck_plan["priority_counts"].items():
            lines.append(f"| `{priority}` | {count} |")
    else:
        lines.append("| n/a | 0 |")
    lines.extend(
        [
            "",
            "| Action | Count |",
            "|---|---:|",
        ]
    )
    for action, count in recheck_plan["action_counts"].items():
        lines.append(f"| `{action}` | {count} |")
    lines.extend(
        [
            "",
            "| Reference | Priority | Action | Reason |",
            "|---|---|---|---|",
        ]
    )
    if recheck_plan["next_rows"]:
        for row in recheck_plan["next_rows"]:
            lines.append(
                f"| `{row['reference']}` | `{row['priority']}` | "
                f"`{row['action']}` | {row['reason']} |"
            )
    else:
        lines.append("| n/a | n/a | n/a | No active rechecks matched the filters. |")
    lines.extend(["", recheck_plan["boundary"]])


def _append_evidence_debt_markdown(
    lines: list[str],
    evidence_debt: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Evidence Debt",
            "",
            f"- Status: `{evidence_debt['status']}`",
            f"- Blocking rows: `{evidence_debt['blocking_rows']}`",
            f"- Archive-only rows: `{evidence_debt['archive_only_rows']}`",
            f"- Highest priority: `{evidence_debt['highest_priority']}`",
            f"- Next action: `{evidence_debt['next_action']}`",
            f"- Outbound action allowed now: `{evidence_debt['payment_route_allowed_now']}`",
            f"- External body allowed: `{evidence_debt['external_body_allowed']}`",
            "",
            "| Action | Count |",
            "|---|---:|",
        ]
    )
    if evidence_debt["action_counts"]:
        for action, count in evidence_debt["action_counts"].items():
            lines.append(f"| `{action}` | {count} |")
    else:
        lines.append("| n/a | 0 |")
    lines.extend(["", "| Platform | Count |", "|---|---:|"])
    if evidence_debt["platform_counts"]:
        for platform, count in evidence_debt["platform_counts"].items():
            lines.append(f"| `{platform}` | {count} |")
    else:
        lines.append("| n/a | 0 |")
    lines.extend(
        [
            "",
            "- References: " + _format_reference_list(evidence_debt["references"]),
            "",
            evidence_debt["boundary"],
        ]
    )


def _append_client_fit_gaps_markdown(
    lines: list[str],
    client_fit_gaps: list[dict[str, Any]],
) -> None:
    lines.extend(
        [
            "",
            "## Client Fit Gaps",
            "",
            "| Reference | Gap codes | Summary |",
            "|---|---|---|",
        ]
    )
    if client_fit_gaps:
        for row in client_fit_gaps:
            gap_codes = ", ".join(f"`{code}`" for code in row["gap_codes"])
            lines.append(f"| `{row['reference']}` | {gap_codes} | {row['gap_summary']} |")
    else:
        lines.append("| n/a | n/a | No rows were excluded by the local client profile. |")
    lines.extend(
        [
            "",
            (
                "Client fit gaps are local decision-support evidence only. They do not "
                "authorize claiming rewards, contacting maintainers, posting comments, or "
                "opening pull requests."
            ),
        ]
    )


def _append_intake_followup_markdown(
    lines: list[str],
    intake_followup: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Intake Follow-Up",
            "",
            f"- Status: `{intake_followup['status']}`",
            f"- Suggested package: `{intake_followup['suggested_package']}`",
            "- Required before paid delivery: "
            f"`{intake_followup['required_before_paid_delivery']}`",
            f"- Next internal action: {intake_followup['next_internal_action']}",
            "",
            "| Field | Required before paid delivery | Reason |",
            "|---|---:|---|",
        ]
    )
    if intake_followup["requested_fields"]:
        for field in intake_followup["requested_fields"]:
            lines.append(
                f"| `{field['field']}` | {field['required_before_paid_delivery']} | "
                f"{field['reason']} |"
            )
    else:
        lines.append("| n/a | False | No additional intake fields are required by this artifact. |")
    lines.extend(["", intake_followup["boundary"]])


def _append_cash_path_status_markdown(
    lines: list[str],
    cash_path_status: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Funding Path Status",
            "",
            f"- Status: `{cash_path_status['status']}`",
            f"- Next internal action: `{cash_path_status['next_revenue_action']}`",
            f"- Copy-brief facts available: `{cash_path_status['copy_brief_facts_available']}`",
            f"- Handoff ready: `{cash_path_status['buyer_ready']}`",
            f"- Outbound action allowed now: `{cash_path_status['payment_route_allowed_now']}`",
            "- Requires written acceptance before any outbound action: "
            f"`{cash_path_status['requires_written_acceptance_before_payment_route']}`",
            "",
            cash_path_status["boundary"],
        ]
    )


def _append_operator_next_steps_markdown(
    lines: list[str],
    operator_next_steps: dict[str, Any],
) -> None:
    lines.extend(
        [
            "",
            "## Operator Next Steps",
            "",
            f"- Status: `{operator_next_steps['status']}`",
            f"- Primary action: `{operator_next_steps['primary_action']}`",
            f"- Copy-brief facts available: `{operator_next_steps['copy_brief_facts_available']}`",
            f"- External body allowed: `{operator_next_steps['external_body_allowed']}`",
            f"- Outbound action allowed now: `{operator_next_steps['payment_route_allowed_now']}`",
            "",
            "| Priority | Action | Source | Scope | Evidence required | Blocks paid delivery | Copy brief allowed | Reason |",
            "|---|---|---|---|---|---:|---:|---|",
        ]
    )
    if operator_next_steps["steps"]:
        for step in operator_next_steps["steps"]:
            lines.append(
                "| "
                f"`{step['priority']}` | "
                f"`{step['action']}` | "
                f"`{step['source']}` | "
                f"{_format_reference_list(step['reference_scope'])} | "
                f"{_format_reference_list(step['evidence_required'])} | "
                f"{step['blocks_paid_delivery']} | "
                f"{step['copy_brief_allowed']} | "
                f"{_escape_markdown_cell(step['reason'])} |"
            )
    else:
        lines.append("| n/a | n/a | n/a | `none` | `none` | False | False | No steps. |")
    lines.extend(["", operator_next_steps["boundary"]])


def _render_funded_issues_report_markdown(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    breakdown = payload["breakdown"]
    moat = payload["no_go_moat"]
    decision = payload["decision_summary"]
    budget = payload["delivery_budget"]
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "# PatchRail Funded Issues Report",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Client profile: `{profile_name}`",
        f"- Safe-only filter: `{payload['safe_only']}`",
        f"- Loaded: `{totals['loaded']}`",
        f"- In scope: `{totals['in_scope']}`",
        f"- Safe to list: `{totals['safe_to_list']}`",
        f"- High risk: `{totals['high_risk']}`",
        f"- Funding known: `{totals['funding_known']}`",
        f"- Funding unknown: `{totals['funding_unknown']}`",
        "",
        "## Decision Summary",
        "",
        f"- Candidate rows: `{decision['candidate_rows']}`",
        f"- No-go rows: `{decision['no_go_rows']}`",
        f"- Funding/state verification needed: `{decision['verification_needed']}`",
        f"- Authorization needed: `{decision['authorization_needed']}`",
        f"- Recommended batch action: {decision['recommended_batch_action']}",
        "",
        "| Decision gate | Count |",
        "|---|---:|",
    ]
    for gate, count in decision["gate_counts"].items():
        lines.append(f"| `{gate}` | {count} |")
    lines.extend(
        [
            "",
            "## Delivery Budget",
            "",
            f"- Suggested package: `{budget['suggested_package']}`",
            f"- Estimated local review: `{budget['estimated_review_minutes']}` minutes",
            f"- Estimated hours: `{budget['estimated_review_hours']}`",
            f"- Max paid hours: `{budget['max_paid_hours']}`",
            f"- Within margin budget: `{budget['within_margin_budget']}`",
            "",
            "| Analysis level | Rows |",
            "|---|---:|",
        ]
    )
    for level, count in budget["analysis_rows"].items():
        lines.append(f"| `{level}` | {count} |")
    _append_delivery_pack_markdown(lines, payload["delivery_pack"])
    _append_source_quality_markdown(lines, payload["source_quality"])
    _append_recheck_plan_markdown(lines, payload["recheck_plan"])
    _append_evidence_debt_markdown(lines, payload["evidence_debt"])
    _append_client_fit_summary_markdown(lines, payload["client_fit_summary"])
    _append_client_fit_gaps_markdown(lines, payload["client_fit_gaps"])
    _append_intake_followup_markdown(lines, payload["intake_followup"])
    _append_cash_path_status_markdown(lines, payload["cash_path_status"])
    _append_operator_next_steps_markdown(lines, payload["operator_next_steps"])
    lines.extend(
        [
            "",
            budget["boundary"],
            "",
            "## No-Go Moat",
            "",
            "| Measure | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(
        [
            f"| High-risk or excluded | {moat['high_risk_or_excluded']} |",
            f"| Missing contribution guidelines | {moat['missing_contribution_guidelines']} |",
            f"| Ambiguous scope | {moat['ambiguous_scope']} |",
            f"| Spam-attractive signals | {moat['spam_attractive']} |",
            f"| Funding unknown | {moat['funding_unknown']} |",
            f"| Stale or closed | {moat['stale_or_closed']} |",
            "",
            "## Breakdowns",
            "",
            "### Risk Levels",
            "",
        ]
    )
    for risk_level, count in breakdown["risk_levels"].items():
        lines.append(f"- `{risk_level}`: `{count}`")
    lines.extend(["", "### Platforms", ""])
    for platform, count in breakdown["platforms"].items():
        lines.append(f"- `{platform}`: `{count}`")
    lines.extend(["", "### Languages", ""])
    for language, count in breakdown["languages"].items():
        lines.append(f"- `{language}`: `{count}`")
    lines.extend(["", "### Opportunity States", ""])
    for opportunity_state, count in breakdown["opportunity_states"].items():
        lines.append(f"- `{opportunity_state}`: `{count}`")
    lines.extend(["", "### Risk Flags", ""])
    if breakdown["risk_flags"]:
        for flag, count in breakdown["risk_flags"].items():
            lines.append(f"- `{flag}`: `{count}`")
    else:
        lines.append("- No risk flags recorded.")
    lines.extend(["", "## Top Safe Candidates", ""])
    candidates = payload["top_safe_candidates"]
    if candidates:
        for candidate in candidates:
            lines.extend(
                [
                    f"### {candidate['reference']}",
                    "",
                    f"- Title: {candidate['title']}",
                    f"- Platform: `{candidate['platform']}`",
                    f"- Funding: `{candidate['funding']}`",
                    f"- Opportunity state: `{candidate['opportunity_state']}`",
                    f"- Risk level: `{candidate['risk_level']}`",
                    f"- URL: {candidate['url']}",
                    "",
                ]
            )
    else:
        lines.append("No safe candidates matched the filters.")
    lines.extend(
        [
            "## Boundary",
            "",
            payload["boundary"],
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _render_funded_issues_score_text(payload: dict[str, Any]) -> str:
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "PatchRail Funded Issues Score",
        f"Client profile: {profile_name}",
        f"Loaded: {payload['total_loaded']}",
        f"Scored: {payload['total_scored']}",
        "Read-only: True",
    ]
    for row in payload["scores"]:
        issue = row["issue"]
        lines.append(
            f"{issue['reference']}: {row['score']} ({row['rating']}) "
            f"[confidence {row['confidence']}; {row['decision_gate']}; "
            f"{', '.join(row['reason_codes'])}] - "
            f"{row['recommended_next_step']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_score_markdown(payload: dict[str, Any]) -> str:
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "# PatchRail Funded Issues Score",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Client profile: `{profile_name}`",
        f"- Safe-only filter: `{payload['safe_only']}`",
        f"- Loaded: `{payload['total_loaded']}`",
        f"- Scored: `{payload['total_scored']}`",
        "",
        "## Rating Counts",
        "",
    ]
    if payload["rating_counts"]:
        lines.extend(
            f"- `{rating}`: `{count}`" for rating, count in payload["rating_counts"].items()
        )
    else:
        lines.append("- No issues matched the filters.")
    lines.extend(["", "## Scores", ""])
    for row in payload["scores"]:
        issue = row["issue"]
        lines.extend(
            [
                f"### {issue['reference']}",
                "",
                f"- Score: `{row['score']}`",
                f"- Confidence: `{row['confidence']}`",
                f"- Rating: `{row['rating']}`",
                f"- Decision gate: `{row['decision_gate']}`",
                f"- Title: {issue['title']}",
                f"- Platform: `{issue['platform']}`",
                f"- Funding: `{issue['funding']['display']}`",
                f"- Opportunity state: `{issue['opportunity_state']}`",
                f"- Risk level: `{issue['risk_level']}`",
                f"- URL: {issue['url']}",
                "- Reason codes: " + ", ".join(f"`{code}`" for code in row["reason_codes"]),
                f"- Recommended next step: {row['recommended_next_step']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            payload["boundary"],
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _render_funded_issues_shortlist_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    moat = payload["no_go_moat"]
    decision = payload["decision_summary"]
    budget = payload["delivery_budget"]
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "PatchRail Funded Issues Shortlist",
        f"Client profile: {profile_name}",
        f"Loaded: {summary['total_loaded']}",
        f"Scored: {summary['total_scored']}",
        f"Candidates: {len(payload['shortlist'])}",
        f"No-go evidence: {len(payload['no_go_evidence'])}",
        (
            "No-go moat: "
            f"{moat['high_risk_or_excluded']} high-risk/excluded, "
            f"{moat['ambiguous_scope']} ambiguous scope"
        ),
        (
            "Decision summary: "
            f"{decision['candidate_rows']} candidates, "
            f"{decision['no_go_rows']} no-go rows, "
            f"{decision['verification_needed']} funding/state rechecks"
        ),
        f"Recommended batch action: {decision['recommended_batch_action']}",
        (
            "Delivery budget: "
            f"{budget['suggested_package']}, "
            f"{budget['estimated_review_minutes']} min local review, "
            f"within margin budget: {budget['within_margin_budget']}"
        ),
        _delivery_pack_summary(payload["delivery_pack"]),
        _source_quality_summary(payload["source_quality"]),
        _recheck_plan_summary(payload["recheck_plan"]),
        _evidence_debt_summary(payload["evidence_debt"]),
        _client_fit_summary_line(payload["client_fit_summary"]),
        f"Client fit gaps: {len(payload['client_fit_gaps'])}",
        _intake_followup_summary(payload["intake_followup"]),
        _cash_path_summary(payload["cash_path_status"]),
        _operator_next_steps_summary(payload["operator_next_steps"]),
        "Read-only: True",
        "Boundary: Decision support only.",
    ]
    for row in payload["shortlist"]:
        issue = row["issue"]
        lines.append(
            f"{issue['reference']}: {row['score']} "
            f"(confidence {row['confidence']}; {row['rating']}; {row['decision_gate']})"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_shortlist_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    moat = payload["no_go_moat"]
    decision = payload["decision_summary"]
    budget = payload["delivery_budget"]
    profile_name = _funded_issues_profile_name(payload["filters"])
    lines = [
        "# PatchRail Funded Issues Shortlist",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Client profile: `{profile_name}`",
        f"- Safe-only candidate filter: `{payload['safe_only']}`",
        f"- Limit: `{payload['limit']}`",
        f"- Loaded: `{summary['total_loaded']}`",
        f"- Scored: `{summary['total_scored']}`",
        f"- Safe to list: `{summary['safe_to_list']}`",
        f"- High risk: `{summary['high_risk']}`",
        "",
        "## Decision Summary",
        "",
        f"- Candidate rows: `{decision['candidate_rows']}`",
        f"- No-go rows: `{decision['no_go_rows']}`",
        f"- Funding/state verification needed: `{decision['verification_needed']}`",
        f"- Authorization needed: `{decision['authorization_needed']}`",
        f"- Recommended batch action: {decision['recommended_batch_action']}",
        "",
        "| Decision gate | Count |",
        "|---|---:|",
    ]
    for gate, count in decision["gate_counts"].items():
        lines.append(f"| `{gate}` | {count} |")
    lines.extend(
        [
            "",
            "## Delivery Budget",
            "",
            f"- Suggested package: `{budget['suggested_package']}`",
            f"- Estimated local review: `{budget['estimated_review_minutes']}` minutes",
            f"- Estimated hours: `{budget['estimated_review_hours']}`",
            f"- Max paid hours: `{budget['max_paid_hours']}`",
            f"- Within margin budget: `{budget['within_margin_budget']}`",
            "",
            "| Analysis level | Rows |",
            "|---|---:|",
        ]
    )
    for level, count in budget["analysis_rows"].items():
        lines.append(f"| `{level}` | {count} |")
    _append_delivery_pack_markdown(lines, payload["delivery_pack"])
    _append_source_quality_markdown(lines, payload["source_quality"])
    _append_recheck_plan_markdown(lines, payload["recheck_plan"])
    _append_evidence_debt_markdown(lines, payload["evidence_debt"])
    _append_client_fit_summary_markdown(lines, payload["client_fit_summary"])
    _append_client_fit_gaps_markdown(lines, payload["client_fit_gaps"])
    _append_intake_followup_markdown(lines, payload["intake_followup"])
    _append_cash_path_status_markdown(lines, payload["cash_path_status"])
    _append_operator_next_steps_markdown(lines, payload["operator_next_steps"])
    lines.extend(
        [
            "",
            budget["boundary"],
            "",
            "## Shortlist",
            "",
        ]
    )
    if payload["shortlist"]:
        for row in payload["shortlist"]:
            issue = row["issue"]
            lines.extend(
                [
                    f"### {issue['reference']}",
                    "",
                    f"- Score: `{row['score']}`",
                    f"- Confidence: `{row['confidence']}`",
                    f"- Rating: `{row['rating']}`",
                    f"- Decision gate: `{row['decision_gate']}`",
                    f"- Title: {issue['title']}",
                    f"- Platform: `{issue['platform']}`",
                    f"- Funding: `{issue['funding']['display']}`",
                    f"- Opportunity state: `{issue['opportunity_state']}`",
                    f"- Risk level: `{issue['risk_level']}`",
                    "- Reason codes: " + ", ".join(f"`{code}`" for code in row["reason_codes"]),
                    f"- Recommended next step: {row['recommended_next_step']}",
                    f"- URL: {issue['url']}",
                    "",
                ]
            )
    else:
        lines.append("No go-candidate or watchlist issues matched the filters.")
    lines.extend(
        [
            "## No-Go Evidence",
            "",
        ]
    )
    if payload["no_go_evidence"]:
        for row in payload["no_go_evidence"]:
            issue = row["issue"]
            lines.extend(
                [
                    f"### {issue['reference']}",
                    "",
                    f"- Score: `{row['score']}`",
                    f"- Confidence: `{row['confidence']}`",
                    f"- Rating: `{row['rating']}`",
                    f"- Decision gate: `{row['decision_gate']}`",
                    f"- Title: {issue['title']}",
                    f"- Opportunity state: `{issue['opportunity_state']}`",
                    f"- Risk level: `{issue['risk_level']}`",
                    "- Reason codes: " + ", ".join(f"`{code}`" for code in row["reason_codes"]),
                    f"- Recommended next step: {row['recommended_next_step']}",
                    "",
                ]
            )
    else:
        lines.append("No no-go rows matched the filters.")
    lines.extend(
        [
            "",
            "## No-Go Moat",
            "",
            "| Measure | Count |",
            "|---|---:|",
            f"| High-risk or excluded | {moat['high_risk_or_excluded']} |",
            f"| Missing contribution guidelines | {moat['missing_contribution_guidelines']} |",
            f"| Ambiguous scope | {moat['ambiguous_scope']} |",
            f"| Spam-attractive signals | {moat['spam_attractive']} |",
            f"| Funding unknown | {moat['funding_unknown']} |",
            "",
            "## Boundary",
            "",
            payload["boundary"],
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _client_report_section_headers() -> list[str]:
    return [
        "## 1. Executive summary",
        "## 2. Top recommendations",
        "## 3. Watchlist",
        "## 4. No-go list",
        "## 5. No-go moat evidence",
        "## 6. Patterns observed",
        "## 7. Recommended operating procedure",
        "## 8. Disclaimer",
    ]


def _render_funded_issues_client_report_text(payload: dict[str, Any]) -> str:
    summary = payload["executive_summary"]
    lines = [
        "PatchRail Opportunity Shortlist",
        f"Prepared for: {payload['client_name']}",
        f"Prepared by: {payload['prepared_by']}",
        f"Date: {payload['date']}",
        f"Scope: {payload['scope']}",
        "",
        "Executive summary",
        f"- Reviewed: {summary['reviewed']}",
        f"- Go: {summary['go']}",
        f"- Watchlist: {summary['watchlist']}",
        f"- No-go: {summary['no_go']}",
        f"- Actionable: {summary['actionable_percent']}%",
        f"- Top recommendation: {summary['top_recommendation'] or 'none'}",
    ]
    dominant = summary["dominant_no_go_reason"]
    if dominant:
        lines.append(
            "- Main reason for no-go decisions: "
            f"{dominant['reason_code']} ({dominant['count']} of {dominant['of_total']})"
        )
    else:
        lines.append("- Main reason for no-go decisions: none")
    lines.append("")
    lines.append("Top recommendations")
    if payload["top_recommendations"]:
        for row in payload["top_recommendations"]:
            lines.append(
                f"- {row['reference']} — {row['payout']} — {row['decision']} "
                f"(confidence {row['confidence']})"
            )
    else:
        lines.append("- No Go candidates matched the filters.")
    lines.append("")
    lines.append("Watchlist")
    if payload["watchlist"]:
        for row in payload["watchlist"]:
            lines.append(f"- {row['reference']} — {row['payout']} — {row['blocker']}")
    else:
        lines.append("- No watchlist items matched the filters.")
    lines.append("")
    lines.append("No-go list")
    if payload["no_go_list"]:
        for row in payload["no_go_list"]:
            lines.append(f"- {row['reference']} — {row['payout']} — {row['reason_code']}")
    else:
        lines.append("- No no-go rows matched the filters.")
    lines.append("")
    lines.append("Disclaimer")
    lines.append(payload["disclaimer"])
    return "\n".join(lines) + "\n"


def _render_funded_issues_client_report_markdown(payload: dict[str, Any]) -> str:
    summary = payload["executive_summary"]
    moat = payload["no_go_moat_evidence"]
    patterns = payload["patterns_observed"]
    lines = [
        "# PatchRail Opportunity Shortlist",
        "",
        f"Prepared for: {payload['client_name']}",
        f"Prepared by: {payload['prepared_by']}",
        f"Scope: {payload['scope']}",
        f"Date: {payload['date']}",
        "",
        "---",
        "",
        "## 1. Executive summary",
        "",
        f"- Reviewed: {summary['reviewed']} funded open-source issues",
        f"- Actionable (Go): {summary['go']}",
        f"- Watchlist: {summary['watchlist']}",
        f"- No-go: {summary['no_go']}",
        f"- Top recommendation: {summary['top_recommendation'] or 'none'}",
    ]
    dominant = summary["dominant_no_go_reason"]
    if dominant:
        lines.append(
            "- Main reason for no-go decisions: "
            f"`{dominant['reason_code']}` ({dominant['count']} of {dominant['of_total']})"
        )
    else:
        lines.append("- Main reason for no-go decisions: none")
    lines.extend(
        [
            "",
            f"The signal-to-noise ratio in this batch was ~{summary['actionable_percent']}% "
            "actionable. The review layer below filters stale, unclear, already-contested, "
            "low-ROI, or authorization-heavy opportunities before engineering time is spent.",
            "",
            "---",
            "",
            "## 2. Top recommendations",
            "",
        ]
    )
    if payload["top_recommendations"]:
        for index, row in enumerate(payload["top_recommendations"], start=1):
            lines.append(f"### {index}. {row['reference']} — {row['payout']} — {row['decision']}")
            lines.append("")
            lines.append(f"- Title: {row['title']}")
            lines.append(f"- URL: {row['url']}")
            lines.append(f"- Platform: {row['platform']}")
            lines.append(f"- Language/stack: {row['language'] or 'unspecified'}")
            lines.append(f"- Current state: {row['state']}")
            lines.append(f"- Maintainer activity: {row['maintainer_activity']}")
            lines.append(f"- Scope clarity: {row['scope']}")
            lines.append(f"- Risk: {row['risk']}")
            if row["effort"]:
                lines.append(f"- Estimated effort: {row['effort']}")
            lines.append(f"- Recommended next step: {row['recommended_next_step']}")
            lines.append(f"- Confidence: {row['confidence']}")
            lines.append("")
    else:
        lines.append("No Go candidates matched the filters.")
        lines.append("")
    lines.extend(
        [
            "---",
            "",
            "## 3. Watchlist",
            "",
            "Issues that may become actionable after clarification or maintainer response.",
            "",
        ]
    )
    if payload["watchlist"]:
        lines.append("| Issue | Payout | Blocker | Trigger to promote |")
        lines.append("|---|---:|---|---|")
        for row in payload["watchlist"]:
            lines.append(
                "| "
                f"[{_escape_markdown_cell(row['reference'])}]({row['url']}) | "
                f"{_escape_markdown_cell(row['payout'])} | "
                f"{_escape_markdown_cell(row['blocker'])} | "
                f"{_escape_markdown_cell(row['trigger_to_promote'])} |"
            )
    else:
        lines.append("No watchlist items matched the filters.")
    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. No-go list",
            "",
        ]
    )
    if payload["no_go_list"]:
        lines.append("| Issue | Payout | Reason code | Evidence |")
        lines.append("|---|---:|---|---|")
        for row in payload["no_go_list"]:
            lines.append(
                "| "
                f"[{_escape_markdown_cell(row['reference'])}]({row['url']}) | "
                f"{_escape_markdown_cell(row['payout'])} | "
                f"`{_escape_markdown_cell(row['reason_code'])}` | "
                f"{_escape_markdown_cell(row['evidence'])} |"
            )
    else:
        lines.append("No no-go rows matched the filters.")
    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. No-go moat evidence",
            "",
            "The numbers below make the review layer visible: public links are only useful "
            "after they survive state, funding, competition, scope and risk checks.",
            "",
            "| Measure | Count |",
            "|---|---:|",
            f"| Raw public results reviewed | {moat['raw_results_reviewed']} |",
            f"| In-scope results reviewed | {moat['in_scope_reviewed']} |",
            f"| High-risk or excluded | {moat['high_risk_or_excluded']} |",
            f"| Missing contribution guidelines | {moat['missing_contribution_guidelines']} |",
            f"| Ambiguous scope | {moat['ambiguous_scope']} |",
            f"| Spam-attractive signals | {moat['spam_attractive']} |",
            f"| Funding unclear | {moat['funding_unknown']} |",
            f"| Stale or closed | {moat['stale_or_closed']} |",
            f"| Final Go candidates | {moat['final_go_candidates']} |",
            "",
            "---",
            "",
            "## 6. Patterns observed",
            "",
        ]
    )
    if patterns["no_go_reason_code_counts"]:
        reason_summary = ", ".join(
            f"`{code}` ({count})" for code, count in patterns["no_go_reason_code_counts"].items()
        )
        lines.append(f"- **No-go reason codes:** {reason_summary}")
    if patterns["go_platform_counts"]:
        go_platforms = ", ".join(
            f"{platform} ({count})" for platform, count in patterns["go_platform_counts"].items()
        )
        lines.append(f"- **Platforms with Go picks:** {go_platforms}")
    if patterns["go_language_counts"]:
        go_languages = ", ".join(
            f"{language} ({count})" for language, count in patterns["go_language_counts"].items()
        )
        lines.append(f"- **Stacks with highest fit:** {go_languages}")
    moat_highlights = patterns["moat_highlights"]
    lines.append(
        "- **Noise filtered:** "
        f"{moat_highlights['high_risk_or_excluded']} high-risk/excluded, "
        f"{moat_highlights['funding_unknown']} funding unclear, "
        f"{moat_highlights['ambiguous_scope']} ambiguous scope, "
        f"{moat_highlights['stale_or_closed']} stale or closed."
    )
    lines.extend(
        [
            "",
            "---",
            "",
            "## 7. Recommended operating procedure",
            "",
        ]
    )
    lines.extend(f"- {step}" for step in payload["recommended_operating_procedure"])
    lines.extend(
        [
            "",
            "---",
            "",
            "## 8. Disclaimer",
            "",
            payload["disclaimer"],
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_funded_issues_recheck_queue_text(payload: dict[str, Any]) -> str:
    lines = [
        "PatchRail Funded Issues Recheck Queue",
        f"Read-only: {payload['read_only']}",
        f"Loaded: {payload['total_loaded']}",
        f"Scored: {payload['total_scored']}",
        f"Queue limit: {payload['queue_limit']}",
        f"Queue rows before limit: {payload['queue_rows_before_limit']}",
        f"Queue rows: {payload['queue_rows']}",
        f"No-go archive rows: {payload['no_go_archive_rows']}",
        f"Priority counts: {payload['priority_counts']}",
        f"Action counts: {payload['action_counts']}",
        _recheck_focus_batch_summary(payload["focus_batch"]),
        f"Boundary: {payload['boundary']}",
    ]
    for item in payload["items"]:
        lines.append(
            f"{item['priority']} | {item['action']} | {item['reference']} | "
            f"{item['decision_gate']} | {item['funding']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_recheck_queue_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# PatchRail Funded Issues Recheck Queue",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Safe-only: `{payload['safe_only']}`",
        f"- Loaded: `{payload['total_loaded']}`",
        f"- Scored: `{payload['total_scored']}`",
        f"- Queue limit: `{payload['queue_limit']}`",
        f"- Queue rows before limit: `{payload['queue_rows_before_limit']}`",
        f"- Queue rows: `{payload['queue_rows']}`",
        f"- No-go archive rows: `{payload['no_go_archive_rows']}`",
        "",
        "## Focus Batch",
        "",
        f"- Status: `{payload['focus_batch']['status']}`",
        f"- Primary action: `{payload['focus_batch']['primary_action']}`",
        f"- Priority: `{payload['focus_batch']['priority']}`",
        f"- Item count: `{payload['focus_batch']['item_count']}`",
        "- References: " + _format_reference_list(payload["focus_batch"]["references"]),
        f"- Platform counts: `{payload['focus_batch']['platform_counts']}`",
        "",
        "### Evidence Checklist",
        "",
    ]
    if payload["focus_batch"]["evidence_checklist"]:
        lines.extend(f"- {item}" for item in payload["focus_batch"]["evidence_checklist"])
    else:
        lines.append("- No active evidence checks.")
    lines.extend(
        [
            "",
            payload["focus_batch"]["boundary"],
            "",
            "## Queue",
            "",
        ]
    )
    if payload["items"]:
        lines.extend(
            [
                "| Priority | Action | Reference | Funding | Score | Evidence checks |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in payload["items"]:
            checklist = "<br>".join(
                _escape_markdown_cell(check) for check in item["evidence_checklist"]
            )
            lines.append(
                "| "
                f"`{item['priority']}` | "
                f"`{item['action']}` | "
                f"[{item['reference']}]({item['url']}) | "
                f"`{item['funding']}` | "
                f"`{item['score']}` | "
                f"{checklist} |"
            )
    else:
        lines.append("No active recheck rows matched the filters.")
    lines.extend(
        [
            "",
            "## Action Counts",
            "",
            "| Action | Count |",
            "|---|---:|",
        ]
    )
    for action, count in payload["action_counts"].items():
        lines.append(f"| `{action}` | {count} |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            payload["boundary"],
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _recheck_focus_batch_summary(focus_batch: dict[str, Any]) -> str:
    return (
        "Focus batch: "
        f"{focus_batch['status']} | "
        f"{focus_batch['priority']} | "
        f"{focus_batch['primary_action']} | "
        f"{focus_batch['item_count']} rows"
    )


def _render_funded_issues_cash_actions_text(payload: dict[str, Any]) -> str:
    cash_path = payload["cash_path_status"]
    lines = [
        "PatchRail Funded Issues Cash Actions",
        f"Read-only: {payload['read_only']}",
        f"Funding-path status: {cash_path['status']}",
        f"Next internal action: {cash_path['next_revenue_action']}",
        f"Action limit: {payload['action_limit']}",
        f"Actions before limit: {payload['actions_before_limit']}",
        f"Action rows: {payload['action_rows']}",
        f"Outbound action allowed now: {cash_path['payment_route_allowed_now']}",
        _operator_next_steps_summary(payload["operator_next_steps"]),
        f"Boundary: {payload['boundary']}",
    ]
    for item in payload["items"]:
        facts = item["copy_brief_facts"]
        facts_status = "none"
        if facts:
            facts_status = (
                f"{len(facts['key_facts'])} facts, {len(facts['constraints'])} constraints"
            )
        lines.append(
            f"{item['priority']} | {item['action']} | "
            f"copy brief allowed: {item['copy_brief_allowed']} | "
            f"copy brief facts: {facts_status} | "
            f"outbound action allowed now: {item['payment_route_allowed_now']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_cash_actions_markdown(payload: dict[str, Any]) -> str:
    cash_path = payload["cash_path_status"]
    lines = [
        "# PatchRail Funded Issues Cash Actions",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Safe-only: `{payload['safe_only']}`",
        f"- Funding-path status: `{cash_path['status']}`",
        f"- Next internal action: `{cash_path['next_revenue_action']}`",
        f"- Action limit: `{payload['action_limit']}`",
        f"- Actions before limit: `{payload['actions_before_limit']}`",
        f"- Action rows: `{payload['action_rows']}`",
        f"- Copy-brief facts available: `{cash_path['copy_brief_facts_available']}`",
        f"- Outbound action allowed now: `{cash_path['payment_route_allowed_now']}`",
        "",
        "## Actions",
        "",
    ]
    if payload["items"]:
        lines.extend(
            [
                "| Priority | Action | Package | Requested fields | Evidence refs | Copy brief facts | External body | Outbound action | Reason |",
                "|---|---|---|---|---|---|---:|---:|---|",
            ]
        )
        for item in payload["items"]:
            facts = item["copy_brief_facts"]
            facts_summary = "not allowed"
            if facts:
                facts_summary = (
                    f"{len(facts['key_facts'])} facts; "
                    f"forbidden: {_format_reference_list(facts['forbidden_fields'])}"
                )
            lines.append(
                "| "
                f"`{item['priority']}` | "
                f"`{item['action']}` | "
                f"`{item['suggested_package']}` | "
                f"{_format_reference_list(item['requested_fields'])} | "
                f"{_format_reference_list(item['evidence_references'])} | "
                f"{facts_summary} | "
                f"{item['external_body_allowed']} | "
                f"{item['payment_route_allowed_now']} | "
                f"{_escape_markdown_cell(item['reason'])} |"
            )
    else:
        lines.append("No internal cash actions matched the filters.")
    _append_operator_next_steps_markdown(lines, payload["operator_next_steps"])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            payload["boundary"],
            "",
            cash_path["boundary"],
            "",
            "Each row is internal facts-only handoff data, not external prose, and does not "
            "enable any outbound action.",
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _render_funded_issues_fulfillment_packet_text(payload: dict[str, Any]) -> str:
    cash_path = payload["cash_path_status"]
    readiness = payload["delivery_readiness"]
    digest = payload["operations_digest"]
    evidence = payload["evidence_manifest"]
    report_plan = payload["report_assembly_plan"]
    totals = payload["totals"]
    lines = [
        "PatchRail Funded Issues Fulfillment Packet",
        f"Read-only: {payload['read_only']}",
        f"Status: {payload['status']}",
        f"Delivery readiness: {readiness['status']}",
        f"Ready for paid delivery: {readiness['ready_for_paid_delivery']}",
        f"Blocking gates: {readiness['blocking_gates']}",
        f"Suggested package: {payload['suggested_package']}",
        f"Packet limit: {payload['packet_limit']}",
        f"Items before limit: {payload['items_before_limit']}",
        f"Item rows: {payload['item_rows']}",
        f"Candidate references: {totals['candidate_references']}",
        f"Active rechecks: {totals['active_rechecks']}",
        f"Next internal action: {cash_path['next_revenue_action']}",
        f"Outbound action allowed now: {cash_path['payment_route_allowed_now']}",
        f"Operations digest: {digest['status']}",
        f"Operations blocking count: {digest['blocking_count']}",
        f"Next safe local action: {_digest_action_summary(digest['next_safe_local_action'])}",
        f"Evidence manifest: {evidence['status']}",
        f"Evidence blocked artifacts: {evidence['blocked_artifacts']}",
        f"Report assembly plan: {report_plan['status']}",
        f"Report blocked sections: {report_plan['blocked_sections']}",
        _operator_next_steps_summary(payload["operator_next_steps"]),
        f"Boundary: {payload['boundary']}",
    ]
    for item in payload["items"]:
        scope = ", ".join(item["reference_scope"]) or "none"
        lines.append(
            f"{item['priority']} | {item['stage']} | {item['action']} | "
            f"{scope} | blocks paid delivery: {item['blocks_paid_delivery']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fulfillment_packet_markdown(payload: dict[str, Any]) -> str:
    cash_path = payload["cash_path_status"]
    readiness = payload["delivery_readiness"]
    digest = payload["operations_digest"]
    evidence = payload["evidence_manifest"]
    report_plan = payload["report_assembly_plan"]
    totals = payload["totals"]
    handoff = payload["handoff"]
    lines = [
        "# PatchRail Funded Issues Fulfillment Packet",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Safe-only: `{payload['safe_only']}`",
        f"- Status: `{payload['status']}`",
        f"- Suggested package: `{payload['suggested_package']}`",
        f"- Packet limit: `{payload['packet_limit']}`",
        f"- Items before limit: `{payload['items_before_limit']}`",
        f"- Item rows: `{payload['item_rows']}`",
        f"- Candidate references: `{totals['candidate_references']}`",
        f"- Verification references: `{totals['verification_references']}`",
        f"- No-go references: `{totals['no_go_references']}`",
        f"- Active rechecks: `{totals['active_rechecks']}`",
        f"- Source count: `{totals['source_count']}`",
        "",
        "## Funding Path",
        "",
        f"- Next internal action: `{cash_path['next_revenue_action']}`",
        f"- Handoff ready: `{cash_path['buyer_ready']}`",
        f"- Outbound action allowed now: `{cash_path['payment_route_allowed_now']}`",
        "- Requires written acceptance before any outbound action: "
        f"`{cash_path['requires_written_acceptance_before_payment_route']}`",
        "",
        "## QA Gates",
        "",
        "| Gate | Passed | Evidence | Reason |",
        "|---|---:|---|---|",
    ]
    for gate in payload["qa_gates"]:
        lines.append(
            "| "
            f"`{gate['gate']}` | "
            f"{gate['passed']} | "
            f"{_format_reference_list(gate['evidence'])} | "
            f"{_escape_markdown_cell(gate['reason'])} |"
        )
    lines.extend(
        [
            "",
            "## Delivery Readiness",
            "",
            f"- Status: `{readiness['status']}`",
            f"- Ready for paid delivery: `{readiness['ready_for_paid_delivery']}`",
            f"- Next internal action: `{readiness['next_internal_action']}`",
            f"- Outbound action allowed now: `{readiness['payment_route_allowed_now']}`",
            f"- External body allowed: `{readiness['external_body_allowed']}`",
            "- Blocking gates: " + _format_reference_list(readiness["blocking_gates"]),
            "- Blocking item actions: "
            + _format_reference_list(readiness["blocking_item_actions"]),
            "- Blocking reference scope: "
            + _format_reference_list(readiness["blocking_reference_scope"]),
            "",
            readiness["boundary"],
            "",
            "## Operations Digest",
            "",
            f"- Status: `{digest['status']}`",
            f"- Blocking count: `{digest['blocking_count']}`",
            f"- Gate pass rate: `{digest['gate_pass_rate']}`",
            "- Next blocker: " + _digest_action_summary(digest["next_blocker"]),
            "- Next safe local action: " + _digest_action_summary(digest["next_safe_local_action"]),
            f"- Outbound action allowed now: `{digest['payment_route_allowed_now']}`",
            f"- External body allowed: `{digest['external_body_allowed']}`",
            "- Non-blocking actions: " + _format_reference_list(digest["non_blocking_actions"]),
            "",
            "| Source | Owner | Priority | Action | Evidence | Blocks paid delivery |",
            "|---|---|---|---|---|---:|",
        ]
    )
    for step in digest["critical_path"]:
        lines.append(
            "| "
            f"`{step['source']}` | "
            f"`{step['owner']}` | "
            f"`{step['priority']}` | "
            f"`{step['action']}` | "
            f"{_format_reference_list(step['evidence'])} | "
            f"{step['blocks_paid_delivery']} |"
        )
    lines.extend(["", digest["boundary"]])
    lines.extend(
        [
            "",
            "## Evidence Manifest",
            "",
            f"- Status: `{evidence['status']}`",
            f"- Artifact count: `{evidence['artifact_count']}`",
            f"- Required artifact count: `{evidence['required_artifact_count']}`",
            f"- Ready required artifacts: `{evidence['ready_required_artifact_count']}`",
            "- Blocked artifacts: " + _format_reference_list(evidence["blocked_artifacts"]),
            f"- Outbound action allowed now: `{evidence['payment_route_allowed_now']}`",
            f"- External body allowed: `{evidence['external_body_allowed']}`",
            "",
            "| Artifact | Status | Required | Sources | References | Next safe local action |",
            "|---|---|---:|---|---|---|",
        ]
    )
    for artifact in evidence["artifacts"]:
        lines.append(
            "| "
            f"`{artifact['artifact']}` | "
            f"`{artifact['status']}` | "
            f"{artifact['required_before_delivery']} | "
            f"{_format_reference_list(artifact['source_fields'])} | "
            f"{_format_reference_list(artifact['references'])} | "
            f"{_escape_markdown_cell(artifact['next_safe_local_action'])} |"
        )
    lines.extend(["", evidence["boundary"]])
    lines.extend(
        [
            "",
            "## Report Assembly Plan",
            "",
            f"- Status: `{report_plan['status']}`",
            f"- Internal assembly ready: `{report_plan['internal_assembly_ready']}`",
            f"- Customer delivery ready: `{report_plan['customer_delivery_ready']}`",
            f"- Section count: `{report_plan['section_count']}`",
            "- Ready sections: " + _format_reference_list(report_plan["ready_sections"]),
            "- Blocked sections: " + _format_reference_list(report_plan["blocked_sections"]),
            f"- Source quality status: `{report_plan['source_quality_status']}`",
            "- Candidate references: "
            + _format_reference_list(report_plan["candidate_references"]),
            "- Verification references: "
            + _format_reference_list(report_plan["verification_references"]),
            "- No-go references: " + _format_reference_list(report_plan["no_go_references"]),
            f"- No-go signal count: `{report_plan['no_go_signal_count']}`",
            f"- Outbound action allowed now: `{report_plan['payment_route_allowed_now']}`",
            f"- External body allowed: `{report_plan['external_body_allowed']}`",
            f"- Customer-facing prose allowed: `{report_plan['customer_facing_prose_allowed']}`",
            "",
            "| Section | Status | Sources | References | Blocked by | Next safe local action |",
            "|---|---|---|---|---|---|",
        ]
    )
    for section in report_plan["sections"]:
        lines.append(
            "| "
            f"`{section['section']}` | "
            f"`{section['status']}` | "
            f"{_format_reference_list(section['source_fields'])} | "
            f"{_format_reference_list(section['references'])} | "
            f"{_format_reference_list(section['blocked_by'])} | "
            f"{_escape_markdown_cell(section['next_safe_local_action'])} |"
        )
    lines.extend(["", report_plan["boundary"]])
    _append_operator_next_steps_markdown(lines, payload["operator_next_steps"])
    lines.extend(["", "## Fulfillment Items", ""])
    if payload["items"]:
        lines.extend(
            [
                "| Priority | Stage | Action | Scope | Evidence required | Blocks paid delivery |",
                "|---|---|---|---|---|---:|",
            ]
        )
        for item in payload["items"]:
            lines.append(
                "| "
                f"`{item['priority']}` | "
                f"`{item['stage']}` | "
                f"`{item['action']}` | "
                f"{_format_reference_list(item['reference_scope'])} | "
                f"{_format_reference_list(item['evidence_required'])} | "
                f"{item['blocks_paid_delivery']} |"
            )
    else:
        lines.append("No internal fulfillment items matched the filters.")
    lines.extend(
        [
            "",
            "## Handoff",
            "",
            "- Candidate references: " + _format_reference_list(handoff["candidate_references"]),
            "- Verification references: "
            + _format_reference_list(handoff["verification_references"]),
            "- No-go references: " + _format_reference_list(handoff["no_go_references"]),
            "- Sections: " + _format_reference_list(handoff["sections"]),
            f"- External body allowed: `{handoff['external_body_allowed']}`",
            f"- Outbound action allowed now: `{handoff['payment_route_allowed_now']}`",
            "- Requires written acceptance before any outbound action: "
            f"`{handoff['requires_written_acceptance_before_payment_route']}`",
            "",
            "## Boundary",
            "",
            payload["boundary"],
            "",
            cash_path["boundary"],
            "",
            "Each row is internal delivery operations data, not customer-facing prose, and "
            "does not enable any outbound action.",
            "",
            "## Blocked Actions",
            "",
        ]
    )
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _digest_action_summary(action: dict[str, Any] | None) -> str:
    if action is None:
        return "`none`"
    evidence = _format_reference_list(action.get("evidence") or [])
    return f"`{action['action']}` ({action['owner']}, {action['priority']}, evidence: {evidence})"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _default_funded_issues_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "issues.json"


def _load_funded_issues_for_cli(source: Path) -> list[Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    return load_funded_issues(source)


def _funded_issues_validate(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        payload = validate_funded_issues(issues)
        payload["source"] = str(source)
        payload["strict"] = bool(args.strict)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        payload = _funded_issues_invalid_validation_payload(source, exc)
        payload["strict"] = bool(args.strict)
    if args.format == "json":
        text = _json_dump(payload)
    else:
        text = _render_funded_issues_validate_text(payload)
    _write_or_print(text, args.out)
    if payload["status"] == "invalid":
        return 1
    if args.strict and payload["warning_count"]:
        return 1
    return 0


def _funded_issues_list(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = summarize_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_markdown(payload)
    elif args.format == "csv":
        text = _render_funded_issues_csv(payload["issues"])
    elif args.format == "jsonl":
        text = _render_funded_issues_jsonl(payload["issues"])
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


def _funded_issues_import(args: argparse.Namespace) -> int:
    try:
        payload = import_provider_export(args.provider, args.source)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid provider export: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_import_markdown(payload)
    else:
        text = _render_funded_issues_text(payload["issues"])
    _write_or_print(text, args.out)
    return 0


def _funded_issues_report(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = report_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_report_markdown(payload)
    else:
        text = _render_funded_issues_report_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_score(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = score_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_score_markdown(payload)
    else:
        text = _render_funded_issues_score_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_shortlist(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = shortlist_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
            limit=args.limit,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_shortlist_markdown(payload)
    else:
        text = _render_funded_issues_shortlist_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_client_report(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = client_report_funded_issues(
            issues,
            client_name=args.client_name,
            report_date=args.date,
            prepared_by=args.prepared_by,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
            limit=args.limit,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "text":
        text = _render_funded_issues_client_report_text(payload)
    else:
        text = _render_funded_issues_client_report_markdown(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_recheck_queue(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = recheck_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
            max_rows=args.max_rows,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_recheck_queue_markdown(payload)
    else:
        text = _render_funded_issues_recheck_queue_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_cash_actions(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = cash_actions_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
            max_actions=args.max_actions,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_cash_actions_markdown(payload)
    else:
        text = _render_funded_issues_cash_actions_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_fulfillment_packet(args: argparse.Namespace) -> int:
    source = args.source or _default_funded_issues_source()
    try:
        issues = _load_funded_issues_for_cli(source)
        profile = load_client_profile(args.profile) if args.profile else None
        payload = fulfillment_packet_funded_issues(
            issues,
            safe_only=not args.include_risky,
            profile=profile,
            platform=args.platform,
            language=args.language,
            min_usd=args.min_usd,
            opportunity_state=args.opportunity_state,
            risk_level=args.risk_level,
            max_items=args.max_items,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_fulfillment_packet_markdown(payload)
    else:
        text = _render_funded_issues_fulfillment_packet_text(payload)
    _write_or_print(text, args.out)
    return 0


def _default_competition_observations_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "competition-observations.json"


def _render_funded_issues_competition_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "PatchRail Funded Issues Competition Signal",
        f"Read-only: {payload['read_only']}",
        f"Reviewed: {summary['reviewed']}",
        f"Noise traps (high+elevated): {summary['noise_traps']}",
        f"High: {summary['high']} | Elevated: {summary['elevated']} | Low: {summary['low']}",
        f"Contested bounty: {summary['contested_bounty']} | "
        f"Crowded no owner: {summary['crowded_no_assignment']}",
    ]
    for result in payload["results"]:
        observed = result["observed"]
        flags = ", ".join(result["risk_flags"]) or "none"
        lines.append(
            f"{result['reference']} | {result['level']} | flags: {flags} | "
            f"PRs: {observed['competing_pr_count']} | "
            f"claimants: {observed['distinct_claimants']} | "
            f"comments: {observed['comment_count']} | "
            f"assigned: {observed['assigned']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_competition_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# PatchRail Funded Issues Competition Signal",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Reviewed: `{summary['reviewed']}`",
        f"- Noise traps (high+elevated): `{summary['noise_traps']}`",
        f"- High: `{summary['high']}` | Elevated: `{summary['elevated']}` | Low: `{summary['low']}`",
        f"- Contested bounty: `{summary['contested_bounty']}` | "
        f"Crowded no owner: `{summary['crowded_no_assignment']}`",
        "",
        "## Results",
        "",
    ]
    if payload["results"]:
        lines.extend(
            [
                "| Reference | Level | Risk flags | PRs | Claimants | Comments | Assigned | Next step |",
                "|---|---|---|---:|---:|---:|---|---|",
            ]
        )
        for result in payload["results"]:
            observed = result["observed"]
            flags = ", ".join(result["risk_flags"]) or "none"
            lines.append(
                "| "
                f"{_escape_markdown_cell(result['reference'])} | "
                f"`{result['level']}` | "
                f"{_escape_markdown_cell(flags)} | "
                f"{observed['competing_pr_count']} | "
                f"{observed['distinct_claimants']} | "
                f"{observed['comment_count']} | "
                f"{observed['assigned']} | "
                f"{_escape_markdown_cell(result['recommended_next_step'])} |"
            )
    else:
        lines.append("No competition observations were provided.")
    lines.extend(["", "## Blocked Actions", ""])
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _funded_issues_competition(args: argparse.Namespace) -> int:
    source = args.source or _default_competition_observations_source()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("observations", raw)
        payload = assess_competition_batch(raw)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid competition observations source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_competition_markdown(payload)
    else:
        text = _render_funded_issues_competition_text(payload)
    _write_or_print(text, args.out)
    return 0


def _default_payout_effort_observations_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "payout-effort-observations.json"


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}"


def _render_funded_issues_payout_effort_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "PatchRail Funded Issues Payout-vs-Effort Signal",
        f"Read-only: {payload['read_only']}",
        f"Reviewed: {summary['reviewed']}",
        f"Underpaid (below floor): {summary['underpaid']}",
        f"Low: {summary['low']} | Marginal: {summary['marginal']} | Strong: {summary['strong']}",
        f"Unknown: {summary['unknown']} | Unverified currency: {summary['unverified_currency']}",
    ]
    for result in payload["results"]:
        observed = result["observed"]
        flags = ", ".join(result["risk_flags"]) or "none"
        lines.append(
            f"{result['reference']} | {result['level']} | flags: {flags} | "
            f"amount: {_format_rate(observed['funding_amount'])} "
            f"{observed['funding_currency']} | "
            f"hours: {_format_rate(observed['estimated_effort_hours'])} | "
            f"rate: {_format_rate(observed['effective_hourly_rate'])} | "
            f"ratio: {_format_rate(observed['payout_effort_ratio'])}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_payout_effort_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# PatchRail Funded Issues Payout-vs-Effort Signal",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Reviewed: `{summary['reviewed']}`",
        f"- Underpaid (below floor): `{summary['underpaid']}`",
        f"- Low: `{summary['low']}` | Marginal: `{summary['marginal']}` | "
        f"Strong: `{summary['strong']}`",
        f"- Unknown: `{summary['unknown']}` | "
        f"Unverified currency: `{summary['unverified_currency']}`",
        "",
        "## Results",
        "",
    ]
    if payload["results"]:
        lines.extend(
            [
                "| Reference | Level | Risk flags | Amount | Hours | Rate (USD/h) | "
                "Ratio | Next step |",
                "|---|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for result in payload["results"]:
            observed = result["observed"]
            flags = ", ".join(result["risk_flags"]) or "none"
            amount = f"{_format_rate(observed['funding_amount'])} {observed['funding_currency']}"
            lines.append(
                "| "
                f"{_escape_markdown_cell(result['reference'])} | "
                f"`{result['level']}` | "
                f"{_escape_markdown_cell(flags)} | "
                f"{_escape_markdown_cell(amount)} | "
                f"{_format_rate(observed['estimated_effort_hours'])} | "
                f"{_format_rate(observed['effective_hourly_rate'])} | "
                f"{_format_rate(observed['payout_effort_ratio'])} | "
                f"{_escape_markdown_cell(result['recommended_next_step'])} |"
            )
    else:
        lines.append("No payout-effort observations were provided.")
    lines.extend(["", "## Blocked Actions", ""])
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _funded_issues_payout_effort(args: argparse.Namespace) -> int:
    source = args.source or _default_payout_effort_observations_source()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("observations", raw)
        payload = assess_payout_effort_batch(raw)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid payout-effort observations source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_payout_effort_markdown(payload)
    else:
        text = _render_funded_issues_payout_effort_text(payload)
    _write_or_print(text, args.out)
    return 0


def _default_staleness_observations_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "staleness-observations.json"


def _format_days(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _render_funded_issues_staleness_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "PatchRail Funded Issues Staleness Signal",
        f"Read-only: {payload['read_only']}",
        f"Reviewed: {summary['reviewed']}",
        f"Stale or dormant: {summary['stale_or_dormant']}",
        f"Active: {summary['active']} | Aging: {summary['aging']} | "
        f"Stale: {summary['stale']} | Dormant: {summary['dormant']} | "
        f"Unknown: {summary['unknown']}",
    ]
    for result in payload["results"]:
        observed = result["observed"]
        flags = ", ".join(result["risk_flags"]) or "none"
        lines.append(
            f"{result['reference']} | {result['level']} | flags: {flags} | "
            f"state: {result['recommended_opportunity_state']} | "
            f"last activity: {_format_days(observed['days_since_last_activity'])}d | "
            f"age: {_format_days(observed['days_since_created'])}d | "
            f"maintainer recent: {observed['maintainer_recently_active']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_staleness_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# PatchRail Funded Issues Staleness Signal",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Reviewed: `{summary['reviewed']}`",
        f"- Stale or dormant: `{summary['stale_or_dormant']}`",
        f"- Active: `{summary['active']}` | Aging: `{summary['aging']}` | "
        f"Stale: `{summary['stale']}` | Dormant: `{summary['dormant']}` | "
        f"Unknown: `{summary['unknown']}`",
        "",
        "## Results",
        "",
    ]
    if payload["results"]:
        lines.extend(
            [
                "| Reference | Level | Risk flags | Recommended state | Last activity (d) | "
                "Age (d) | Maintainer recent | Next step |",
                "|---|---|---|---|---:|---:|---|---|",
            ]
        )
        for result in payload["results"]:
            observed = result["observed"]
            flags = ", ".join(result["risk_flags"]) or "none"
            lines.append(
                "| "
                f"{_escape_markdown_cell(result['reference'])} | "
                f"`{result['level']}` | "
                f"{_escape_markdown_cell(flags)} | "
                f"`{result['recommended_opportunity_state']}` | "
                f"{_format_days(observed['days_since_last_activity'])} | "
                f"{_format_days(observed['days_since_created'])} | "
                f"{observed['maintainer_recently_active']} | "
                f"{_escape_markdown_cell(result['recommended_next_step'])} |"
            )
    else:
        lines.append("No staleness observations were provided.")
    lines.extend(["", "## Blocked Actions", ""])
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _funded_issues_staleness(args: argparse.Namespace) -> int:
    source = args.source or _default_staleness_observations_source()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("observations", raw)
        payload = assess_staleness_batch(raw)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid staleness observations source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_staleness_markdown(payload)
    else:
        text = _render_funded_issues_staleness_text(payload)
    _write_or_print(text, args.out)
    return 0


def _default_testability_observations_source() -> Path:
    return Path("examples") / "funded-issues-readonly" / "testability-observations.json"


def _format_bool(value: bool | None) -> str:
    return "n/a" if value is None else str(value)


def _render_funded_issues_testability_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "PatchRail Funded Issues Testability Signal",
        f"Read-only: {payload['read_only']}",
        f"Reviewed: {summary['reviewed']}",
        f"Unverifiable: {summary['unverifiable']}",
        f"Verifiable: {summary['verifiable']} | "
        f"Partially verifiable: {summary['partially_verifiable']} | "
        f"Unverifiable: {summary['unverifiable']} | "
        f"Unknown: {summary['unknown']}",
    ]
    for result in payload["results"]:
        observed = result["observed"]
        flags = ", ".join(result["risk_flags"]) or "none"
        lines.append(
            f"{result['reference']} | {result['level']} | flags: {flags} | "
            f"failing test: {_format_bool(observed['has_failing_test'])} | "
            f"repro: {_format_bool(observed['has_reproduction_steps'])} | "
            f"logs: {_format_bool(observed['has_stack_trace_or_logs'])} | "
            f"expected/actual: {_format_bool(observed['has_expected_vs_actual'])}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_testability_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# PatchRail Funded Issues Testability Signal",
        "",
        f"- Read-only: `{payload['read_only']}`",
        f"- Reviewed: `{summary['reviewed']}`",
        f"- Unverifiable: `{summary['unverifiable']}`",
        f"- Verifiable: `{summary['verifiable']}` | "
        f"Partially verifiable: `{summary['partially_verifiable']}` | "
        f"Unverifiable: `{summary['unverifiable']}` | "
        f"Unknown: `{summary['unknown']}`",
        "",
        "## Results",
        "",
    ]
    if payload["results"]:
        lines.extend(
            [
                "| Reference | Level | Risk flags | Failing test | Repro | Logs | "
                "Expected/actual | Next step |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for result in payload["results"]:
            observed = result["observed"]
            flags = ", ".join(result["risk_flags"]) or "none"
            lines.append(
                "| "
                f"{_escape_markdown_cell(result['reference'])} | "
                f"`{result['level']}` | "
                f"{_escape_markdown_cell(flags)} | "
                f"{_format_bool(observed['has_failing_test'])} | "
                f"{_format_bool(observed['has_reproduction_steps'])} | "
                f"{_format_bool(observed['has_stack_trace_or_logs'])} | "
                f"{_format_bool(observed['has_expected_vs_actual'])} | "
                f"{_escape_markdown_cell(result['recommended_next_step'])} |"
            )
    else:
        lines.append("No testability observations were provided.")
    lines.extend(["", "## Blocked Actions", ""])
    lines.extend(f"- `{action}`" for action in payload["blocked_actions"])
    return "\n".join(lines) + "\n"


def _funded_issues_testability(args: argparse.Namespace) -> int:
    source = args.source or _default_testability_observations_source()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("observations", raw)
        payload = assess_testability_batch(raw)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid testability observations source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_testability_markdown(payload)
    else:
        text = _render_funded_issues_testability_text(payload)
    _write_or_print(text, args.out)
    return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scored_issue_records(issues: list[Any]) -> list[dict[str, Any]]:
    """Attach the read-only readiness score to each normalized issue record."""

    records: list[dict[str, Any]] = []
    for row in score_funded_issues(issues)["scores"]:
        record = dict(row["issue"])
        record["score"] = row["score"]
        records.append(record)
    return records


def _render_funded_issues_track_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "PatchRail funded-issues tracker store update",
        f"Store: {payload['store']}",
        f"Now: {payload['now']}",
        f"Loaded: {payload['total_loaded']}  Total entries: {payload['total_entries']}",
        (
            f"Added: {summary['added']}  Updated: {summary['updated']}  "
            f"Transitioned: {summary['transitioned']}  Unchanged: {summary['unchanged']}"
        ),
        (
            f"Blocklisted: dropped {summary['blocked']} inbound, "
            f"purged {payload['purged_blocklisted']} existing"
        ),
    ]
    for transition in summary["transitions"]:
        lines.append(f"  - {transition['url']}: {transition['from']} -> {transition['state']}")
    return "\n".join(lines) + "\n"


def _render_funded_issues_track_status_text(payload: dict[str, Any]) -> str:
    lines = [
        "PatchRail funded-issues tracker store status",
        f"Total entries: {payload['total_entries']}",
        "States:",
    ]
    for state, count in sorted(payload["states"].items()):
        lines.append(f"  - {state}: {count}")
    lines.append("Source-noise breakdown:")
    lines.append(f"  - tracked total: {payload['tracked_total']}")
    lines.append(f"  - noise flagged: {payload['noise_flagged']}")
    lines.append(f"  - clean active: {payload['clean_active']}")
    added_24h = payload["added_24h"]
    lines.append(f"Added in last 24h: {'n/a' if added_24h is None else added_24h}")
    total_usd = payload["total_usd"]
    lines.append(
        "Total USD: n/a"
        if total_usd is None
        else f"Total USD: {total_usd} across {payload['usd_entries']} entries"
    )
    return "\n".join(lines) + "\n"


def _funded_issues_track(args: argparse.Namespace) -> int:
    source = args.input or _default_funded_issues_source()
    now = args.now or _now_iso()
    try:
        issues = _load_funded_issues_for_cli(source)
        store = load_store(args.store)
        purge = purge_blocklisted_entries(store)
        records = _scored_issue_records(issues)
        summary = merge_into_store(store, records, now)
        save_store(args.store, store)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue source: {exc}", file=sys.stderr)
        return 1
    payload = {
        "schema_version": "patchrail.funded_issues.track.v1",
        "store": str(args.store),
        "input": str(source),
        "now": now,
        "total_loaded": len(records),
        "total_entries": len(store["entries"]),
        "purged_blocklisted": purge["removed"],
        "summary": summary.to_dict(),
    }
    if args.format == "json":
        text = _json_dump(payload)
    else:
        text = _render_funded_issues_track_text(payload)
    _write_or_print(text, args.out)
    return 0


def _funded_issues_track_status(args: argparse.Namespace) -> int:
    now = args.now or _now_iso()
    try:
        store = load_store(args.store)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue store: {exc}", file=sys.stderr)
        return 1
    payload = store_status(store, now)
    if args.format == "json":
        text = _json_dump(payload)
    else:
        text = _render_funded_issues_track_status_text(payload)
    _write_or_print(text, args.out)
    return 0


def _render_funded_issues_fresh_text(payload: dict[str, Any]) -> str:
    orgs = payload["orgs"]
    scope = "all orgs" if orgs is None else ", ".join(orgs)
    solver_scope = payload.get("solver_status") or "all solver statuses"
    solver_counts = payload.get("solver_counts") or {}
    lines = [
        "PatchRail funded-issues fresh radar (local read-only)",
        (
            f"Window: last {payload['window_hours']}h  Scope: {scope}  "
            f"Solver: {solver_scope}  Sort: {payload.get('sort', 'freshness')}  "
            f"Min age: {payload.get('min_age_minutes') or 0}m  "
            f"Max updated age: {payload.get('max_updated_age_hours') or 'none'}h"
        ),
        (
            f"Considered: {payload['considered']}  "
            f"Fresh: {payload['fresh_count']}  "
            f"Before limit: {payload.get('fresh_count_before_limit', payload['fresh_count'])}  "
            f"Limit: {payload.get('limit') or 'none'}  "
            f"Skipped (no date signal): {payload['skipped_no_signal']}"
        ),
        (
            f"Solver counts: GO {solver_counts.get('go_candidate', 0)}  "
            f"Recheck {solver_counts.get('needs_review', 0)}  "
            f"Skip {solver_counts.get('no_go', 0)}"
        ),
        f"Next safe action: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not payload["fresh"]:
        lines.append("  No bounties posted/labeled within the window.")
        return "\n".join(lines) + "\n"
    for row in payload["fresh"]:
        age_h = row["age_hours"]
        attempts = row["attempt_count"]
        attempts_text = "n/a" if attempts is None else str(attempts)
        blockers = ", ".join(row.get("go_blockers") or ["none"])
        lines.append(
            f"  - {row['reference'] or row['url']}: "
            f"{row['funding_display'] or 'unknown'} "
            f"({age_h:.1f}h via {row['age_basis']}, "
            f"attempts: {attempts_text}, assignees: {row['assignee_count']}, "
            f"solver: {row.get('solver_status', 'needs_review')}, blockers: {blockers})"
        )
        if row.get("title"):
            lines.append(f"      {row['title']}")
    return "\n".join(lines) + "\n"


def _fresh_priority_reason(row: dict[str, Any]) -> str:
    blockers = row.get("go_blockers") or []
    if row.get("solver_status") == "go_candidate":
        return "priority: clean solver candidate"
    if row.get("solver_status") == "needs_review":
        return "review: " + ", ".join(blockers or ["missing manual evidence"])
    return "discard: " + ", ".join(blockers or ["not solver-ready"])


def _fresh_claim_issue_number(row: dict[str, Any]) -> str:
    reference = str(row.get("reference") or "")
    if "#" in reference:
        candidate = reference.rsplit("#", 1)[1].strip()
        if candidate:
            return candidate
    url = str(row.get("url") or "").rstrip("/")
    if "/issues/" in url:
        candidate = url.rsplit("/issues/", 1)[1].split("/", 1)[0].strip()
        if candidate:
            return candidate
    return "<issue-number>"


def _fresh_claim_recheck_command(payload: dict[str, Any], row: dict[str, Any]) -> str:
    parts = [
        "patchrail",
        "funded-issues",
        "fresh",
        "--store",
        str(payload.get("store_path") or "<store>"),
        "--hours",
        str(payload["window_hours"]),
        "--org",
        str(row.get("org") or "<org>"),
        "--solver-status",
        "go_candidate",
        "--sort",
        "solver",
    ]
    if payload.get("min_usd") is not None:
        parts.extend(["--min-usd", f"{float(payload['min_usd']):g}"])
    if payload.get("max_usd") is not None:
        parts.extend(["--max-usd", f"{float(payload['max_usd']):g}"])
    if payload.get("max_attempts") is not None:
        parts.extend(["--max-attempts", str(payload["max_attempts"])])
    if payload.get("max_assignees") is not None:
        parts.extend(["--max-assignees", str(payload["max_assignees"])])
    if payload.get("min_age_minutes") is not None:
        parts.extend(["--min-age-minutes", str(payload["min_age_minutes"])])
    if payload.get("max_updated_age_hours") is not None:
        parts.extend(["--max-updated-age-hours", str(payload["max_updated_age_hours"])])
    if payload.get("require_tests_signal"):
        parts.append("--require-tests-signal")
    parts.extend(["--format", "claim-checklist"])
    return " ".join(shlex.quote(part) for part in parts)


def _fresh_repo_from_row(row: dict[str, Any]) -> str:
    repository = str(row.get("repository") or "").strip()
    if repository:
        return repository
    url = str(row.get("url") or "")
    match = re.match(r"^https://github\.com/([^/]+/[^/]+)/issues/\d+", url)
    if match:
        return match.group(1)
    return "<owner/repo>"


def _fresh_readonly_recheck_command(
    payload: dict[str, Any], row: dict[str, Any], solver_status: str
) -> str:
    parts = [
        "patchrail",
        "funded-issues",
        "fresh",
        "--store",
        str(payload.get("store_path") or "<store>"),
        "--hours",
        str(payload["window_hours"]),
        "--org",
        str(row.get("org") or _fresh_repo_from_row(row).split("/", 1)[0] or "<org>"),
        "--solver-status",
        solver_status,
        "--sort",
        "solver",
    ]
    if payload.get("min_usd") is not None:
        parts.extend(["--min-usd", f"{float(payload['min_usd']):g}"])
    if payload.get("max_usd") is not None:
        parts.extend(["--max-usd", f"{float(payload['max_usd']):g}"])
    if payload.get("max_attempts") is not None:
        parts.extend(["--max-attempts", str(payload["max_attempts"])])
    if payload.get("max_assignees") is not None:
        parts.extend(["--max-assignees", str(payload["max_assignees"])])
    if payload.get("min_age_minutes") is not None:
        parts.extend(["--min-age-minutes", str(payload["min_age_minutes"])])
    if payload.get("max_updated_age_hours") is not None:
        parts.extend(["--max-updated-age-hours", str(payload["max_updated_age_hours"])])
    if payload.get("require_tests_signal"):
        parts.append("--require-tests-signal")
    parts.extend(["--format", "operator-brief"])
    return " ".join(shlex.quote(part) for part in parts)


def _load_solver_allowlist_orgs(path: Path) -> list[str]:
    """Extract GitHub owners from the solver allowlist Markdown table."""

    orgs: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        target = cells[0].strip("` ")
        if not target or target.lower() == "org/repo" or set(target) <= {"-", ":"}:
            continue
        target = target.split()[0].strip("` ")
        match = re.match(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?:\*|[A-Za-z0-9_.-]+)$", target)
        if not match:
            continue
        owner = match.group("owner").lower()
        if owner not in seen:
            seen.add(owner)
            orgs.append(owner)
    if not orgs:
        raise ValueError(f"no solver allowlist orgs found in {path}")
    return orgs


def _default_solver_allowlist_path() -> Path | None:
    for base in (Path.cwd(), *Path.cwd().parents):
        candidate = base / "memory" / "SOLVER_ALLOWLIST.md"
        if candidate.is_file():
            return candidate
    return None


def _apply_fresh_quality_profile(args: argparse.Namespace) -> Path | None:
    if args.quality_profile is None:
        return args.solver_allowlist
    if args.quality_profile != "solver":
        raise ValueError(f"unsupported quality profile: {args.quality_profile}")

    if args.min_usd is None:
        args.min_usd = 25
    if args.max_usd is None:
        args.max_usd = 300
    if args.max_attempts is None:
        args.max_attempts = 3
    if args.min_age_minutes is None:
        args.min_age_minutes = 10
    if args.max_updated_age_hours is None:
        args.max_updated_age_hours = 168
    args.require_tests_signal = True

    if args.solver_allowlist is not None:
        return args.solver_allowlist
    allowlist = _default_solver_allowlist_path()
    if allowlist is None:
        raise ValueError(
            "--quality-profile solver requires --solver-allowlist when memory/SOLVER_ALLOWLIST.md "
            "cannot be found from the current directory"
        )
    args.solver_allowlist = allowlist
    return allowlist


def _render_funded_issues_fresh_markdown(payload: dict[str, Any]) -> str:
    orgs = payload["orgs"]
    scope = "all orgs" if orgs is None else ", ".join(orgs)
    solver_scope = payload.get("solver_status") or "all solver statuses"
    solver_counts = payload.get("solver_counts") or {}
    lines = [
        "# PatchRail Funded Issues Fresh Radar",
        "",
        "- Mode: `local read-only`",
        f"- Window: last `{payload['window_hours']}` hours",
        f"- Scope: `{scope}`",
        f"- Solver filter: `{solver_scope}`",
        f"- Sort: `{payload.get('sort', 'freshness')}`",
        f"- Minimum age: `{payload.get('min_age_minutes') or 0}` minutes",
        f"- Maximum updated age: `{payload.get('max_updated_age_hours') or 'none'}` hours",
        (
            f"- Fresh: `{payload['fresh_count']}` / "
            f"`{payload.get('fresh_count_before_limit', payload['fresh_count'])}` before limit"
        ),
        (
            f"- Solver counts: GO `{solver_counts.get('go_candidate', 0)}` | "
            f"Recheck `{solver_counts.get('needs_review', 0)}` | "
            f"Skip `{solver_counts.get('no_go', 0)}`"
        ),
        f"- Next safe action: `{payload.get('next_safe_action', 'unknown')}`",
        "",
    ]
    if not payload["fresh"]:
        lines.append("No bounties posted/labeled within the window.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Issue | USD | Age | Owner | Solver status | Priority / discard reason |",
            "|---|---:|---:|---|---|---|",
        ]
    )
    for row in payload["fresh"]:
        reference = row.get("reference") or row.get("url") or "unknown"
        url = row.get("url") or ""
        issue = (
            f"[{_escape_markdown_cell(str(reference))}]({url})"
            if url
            else _escape_markdown_cell(str(reference))
        )
        usd = row.get("funding_display") or "unknown"
        age = f"{float(row['age_hours']):.1f}h via {row['age_basis']}"
        lines.append(
            "| "
            f"{issue} | "
            f"{_escape_markdown_cell(str(usd))} | "
            f"{_escape_markdown_cell(age)} | "
            f"{_escape_markdown_cell(str(row.get('org') or 'unknown'))} | "
            f"`{_escape_markdown_cell(str(row.get('solver_status', 'needs_review')))}` | "
            f"{_escape_markdown_cell(_fresh_priority_reason(row))} |"
        )
        if row.get("title"):
            lines.append(f"| {_escape_markdown_cell(str(row['title']))} |  |  |  |  | title |")
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_shortlist_note(payload: dict[str, Any]) -> str:
    now = str(payload.get("now") or "").replace("T", " ").replace("+00:00", "Z")
    lines = [
        f"## BARRIDO {now}",
        (
            f"- filtro: {payload['window_hours']}h, "
            f"{payload.get('min_usd') or 0:g}-{payload.get('max_usd') or 'inf'} USD, "
            f"solver={payload.get('solver_status') or 'all'}, "
            f"sort={payload.get('sort', 'freshness')}, "
            f"min_age={payload.get('min_age_minutes') or 0}m, "
            f"max_updated_age={payload.get('max_updated_age_hours') or 'none'}h"
        ),
        f"- next_safe_action: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not payload["fresh"]:
        lines.append(
            f"- 0 fresh / 0 GO sobre {payload['considered']} tracked; "
            "sin candidato seguro para preparar fix."
        )
        return "\n".join(lines) + "\n"

    go_count = sum(1 for row in payload["fresh"] if row.get("solver_status") == "go_candidate")
    lines.append(
        f"- fresh={payload['fresh_count']} "
        f"(antes_limit={payload.get('fresh_count_before_limit', payload['fresh_count'])}) "
        f"go={go_count}"
    )
    for row in payload["fresh"]:
        reference = row.get("reference") or row.get("url") or "unknown"
        funding = row.get("funding_display") or "unknown"
        title = str(row.get("title") or "").strip()
        title_text = f" - {title}" if title else ""
        lines.append(
            f"- {row.get('solver_status', 'needs_review')}: {reference} - {funding} - "
            f"{float(row['age_hours']):.1f}h via {row['age_basis']} - "
            f"{_fresh_priority_reason(row)} - {row.get('url') or 'no-url'}{title_text}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_go_list(payload: dict[str, Any]) -> str:
    rows = [row for row in payload["fresh"] if row.get("solver_status") == "go_candidate"]
    lines = [
        "PatchRail funded-issues GO candidates",
        (f"Window: {payload['window_hours']}h  Fresh: {payload['fresh_count']}  GO: {len(rows)}"),
    ]
    if not rows:
        lines.append("No clean solver candidates in the current fresh window.")
        return "\n".join(lines) + "\n"
    for row in rows:
        reference = row.get("reference") or row.get("url") or "unknown"
        funding = row.get("funding_display") or "unknown"
        lines.append(
            f"- {reference} | {funding} | {float(row['age_hours']):.1f}h via "
            f"{row['age_basis']} | {row.get('url') or 'no-url'}"
        )
        if row.get("title"):
            lines.append(f"  {row['title']}")
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_csv(payload: dict[str, Any]) -> str:
    fieldnames = [
        "reference",
        "url",
        "repository",
        "org",
        "title",
        "funding_display",
        "age_hours",
        "age_basis",
        "updated_at",
        "updated_age_hours",
        "state",
        "attempt_count",
        "assignee_count",
        "testability_signal",
        "solver_status",
        "go_blockers",
        "next_action",
        "first_seen",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in payload["fresh"]:
        writer.writerow({field: _csv_cell(row.get(field)) for field in fieldnames})
    return buffer.getvalue()


def _render_funded_issues_fresh_jsonl(payload: dict[str, Any]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in payload["fresh"])


def _render_funded_issues_fresh_urls(payload: dict[str, Any]) -> str:
    urls = [
        str(row["url"])
        for row in payload["fresh"]
        if row.get("solver_status") == "go_candidate" and row.get("url")
    ]
    if not urls:
        return ""
    return "\n".join(urls) + "\n"


def _env_value(value: Any) -> str:
    return shlex.quote("" if value is None else str(value))


def _render_funded_issues_fresh_env(payload: dict[str, Any]) -> str:
    solver_counts = payload.get("solver_counts") or {}
    go_rows = [row for row in payload["fresh"] if row.get("solver_status") == "go_candidate"]
    first_go = go_rows[0] if go_rows else {}
    values = {
        "PATCHRAIL_FUNDED_SCHEMA": payload.get("schema_version"),
        "PATCHRAIL_FUNDED_FRESH_COUNT": payload.get("fresh_count", 0),
        "PATCHRAIL_FUNDED_GO_COUNT": solver_counts.get("go_candidate", 0),
        "PATCHRAIL_FUNDED_NEEDS_REVIEW_COUNT": solver_counts.get("needs_review", 0),
        "PATCHRAIL_FUNDED_NO_GO_COUNT": solver_counts.get("no_go", 0),
        "PATCHRAIL_FUNDED_NEXT_SAFE_ACTION": payload.get("next_safe_action"),
        "PATCHRAIL_FUNDED_FIRST_GO_REFERENCE": first_go.get("reference"),
        "PATCHRAIL_FUNDED_FIRST_GO_URL": first_go.get("url"),
        "PATCHRAIL_FUNDED_FIRST_GO_NEXT_ACTION": first_go.get("next_action"),
    }
    return "".join(f"{key}={_env_value(value)}\n" for key, value in values.items())


def _render_funded_issues_fresh_signal(payload: dict[str, Any]) -> str:
    rows = list(payload["fresh"])
    go_rows = [row for row in rows if row.get("solver_status") == "go_candidate"]
    review_rows = [row for row in rows if row.get("solver_status") == "needs_review"]
    skip_rows = [row for row in rows if row.get("solver_status") == "no_go"]
    if go_rows:
        row = go_rows[0]
        reference = row.get("reference") or row.get("url") or "unknown"
        return (
            "CLAIM_READY "
            f"count={len(go_rows)} "
            f"reference={shlex.quote(str(reference))} "
            f"url={shlex.quote(str(row.get('url') or ''))} "
            f"next_action={shlex.quote(str(row.get('next_action') or 'prepare_fix_and_claim_pr'))}"
            "\n"
        )
    if review_rows:
        row = review_rows[0]
        reference = row.get("reference") or row.get("url") or "unknown"
        blockers = ",".join(row.get("go_blockers") or ["missing_current_issue_evidence"])
        return (
            "RECHECK_ONLY "
            f"count={len(review_rows)} "
            f"reference={shlex.quote(str(reference))} "
            f"url={shlex.quote(str(row.get('url') or ''))} "
            f"reason={shlex.quote(blockers)}\n"
        )
    if skip_rows:
        return f"SKIP_ONLY count={len(skip_rows)} next_action=wait_for_fresh_funded_issue\n"
    return "WAIT count=0 next_action=wait_for_fresh_funded_issue\n"


def _one_line_field(value: Any) -> str:
    text = "" if value is None else str(value)
    return shlex.quote(text.replace("\n", " ").strip())


def _render_funded_issues_fresh_one_line(payload: dict[str, Any]) -> str:
    solver_counts = payload.get("solver_counts") or {}
    rows = list(payload["fresh"])
    go_rows = [row for row in rows if row.get("solver_status") == "go_candidate"]
    review_rows = [row for row in rows if row.get("solver_status") == "needs_review"]
    if go_rows:
        state = "CLAIM_READY"
        first = go_rows[0]
    elif review_rows:
        state = "RECHECK_ONLY"
        first = review_rows[0]
    elif rows:
        state = "SKIP_ONLY"
        first = rows[0]
    else:
        state = "WAIT"
        first = {}
    reference = first.get("reference") or first.get("url") or ""
    return (
        f"{state} "
        f"fresh={payload['fresh_count']} "
        f"go={solver_counts.get('go_candidate', 0)} "
        f"recheck={solver_counts.get('needs_review', 0)} "
        f"skip={solver_counts.get('no_go', 0)} "
        f"first={_one_line_field(reference)} "
        f"url={_one_line_field(first.get('url'))} "
        f"next={_one_line_field(payload.get('next_safe_action'))}\n"
    )


def _render_funded_issues_fresh_digest(payload: dict[str, Any]) -> str:
    solver_counts = payload.get("solver_counts") or {}
    rows = list(payload["fresh"])
    go_rows = [row for row in rows if row.get("solver_status") == "go_candidate"]
    review_rows = [row for row in rows if row.get("solver_status") == "needs_review"]
    if go_rows:
        state = "CLAIM_READY"
        first = go_rows[0]
    elif review_rows:
        state = "RECHECK_ONLY"
        first = review_rows[0]
    elif rows:
        state = "SKIP_ONLY"
        first = rows[0]
    else:
        state = "WAIT"
        first = {}

    lines = [
        f"{state}: fresh={payload['fresh_count']} go={solver_counts.get('go_candidate', 0)} "
        f"recheck={solver_counts.get('needs_review', 0)} skip={solver_counts.get('no_go', 0)}",
        f"Next: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not first:
        lines.append("Candidate: none")
        return "\n".join(lines) + "\n"

    reference = first.get("reference") or first.get("url") or "unknown"
    blockers = ", ".join(first.get("go_blockers") or ["none"])
    lines.extend(
        [
            f"Candidate: {reference} ({first.get('funding_display') or 'unknown'})",
            f"URL: {first.get('url') or 'no-url'}",
            f"Age: {float(first['age_hours']):.1f}h via {first['age_basis']}",
            f"Blockers: {blockers}",
        ]
    )
    status = str(first.get("solver_status") or "needs_review")
    if status in {"go_candidate", "needs_review"}:
        repo = _fresh_repo_from_row(first)
        issue_number = _fresh_claim_issue_number(first)
        lines.append(
            "Recheck: "
            f"gh issue view {shlex.quote(issue_number)} --repo {shlex.quote(repo)} "
            "--json state,assignees,comments,labels,updatedAt"
        )
    lines.append("Boundary: read-only digest; no PR, claim, comment, or maintainer contact.")
    return "\n".join(lines) + "\n"


def _github_annotation_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _github_annotation_message_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _render_funded_issues_fresh_github_annotations(payload: dict[str, Any]) -> str:
    rows = list(payload["fresh"])
    if not rows:
        return (
            "::notice title=PatchRail funded issues::"
            "WAIT count=0 next_action=wait_for_fresh_funded_issue\n"
        )

    lines: list[str] = []
    for row in rows:
        status = row.get("solver_status", "needs_review")
        if status == "go_candidate":
            level = "warning"
            title = "PatchRail claim-ready funded issue"
        elif status == "needs_review":
            level = "notice"
            title = "PatchRail funded issue needs recheck"
        else:
            level = "notice"
            title = "PatchRail funded issue skipped"
        reference = row.get("reference") or row.get("url") or "unknown"
        blockers = ", ".join(row.get("go_blockers") or ["none"])
        message = (
            f"{status}: {reference} | {row.get('funding_display') or 'unknown'} | "
            f"{float(row['age_hours']):.1f}h via {row['age_basis']} | "
            f"next={row.get('next_action') or 'wait_for_fresh_funded_issue'} | "
            f"blockers={blockers} | {row.get('url') or 'no-url'}"
        )
        lines.append(
            f"::{level} title={_github_annotation_escape(title)}::"
            f"{_github_annotation_message_escape(message)}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_recheck_commands(payload: dict[str, Any]) -> str:
    rows = [
        row
        for row in payload["fresh"]
        if row.get("solver_status") in {"go_candidate", "needs_review"}
    ]
    lines = [
        "# PatchRail funded-issues read-only recheck commands",
        f"# Window: {payload['window_hours']}h; next_safe_action={payload.get('next_safe_action')}",
    ]
    if not rows:
        lines.append("# WAIT: no GO or recheck candidates in the current fresh window.")
        return "\n".join(lines) + "\n"
    for row in rows:
        status = str(row.get("solver_status") or "needs_review")
        reference = row.get("reference") or row.get("url") or "unknown"
        repo = _fresh_repo_from_row(row)
        issue_number = _fresh_claim_issue_number(row)
        lines.extend(
            [
                "",
                f"# {status}: {reference}",
                (
                    "gh issue view "
                    f"{shlex.quote(issue_number)} --repo {shlex.quote(repo)} "
                    "--json state,assignees,comments,labels,updatedAt"
                ),
                _fresh_readonly_recheck_command(payload, row, status),
            ]
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_review_watch(payload: dict[str, Any]) -> str:
    rows = [row for row in payload["fresh"] if row.get("solver_status") == "needs_review"]
    lines = [
        "PatchRail funded-issues review watch",
        (
            f"Window: {payload['window_hours']}h  Fresh: {payload['fresh_count']}  "
            f"Review: {len(rows)}"
        ),
        "Mode: read-only recheck before any branch, PR, claim, or maintainer contact.",
    ]
    if not rows:
        lines.append("WAIT: no near-miss candidates need manual recheck in this fresh window.")
        return "\n".join(lines) + "\n"
    for index, row in enumerate(rows, start=1):
        reference = row.get("reference") or row.get("url") or "unknown"
        blockers = ", ".join(row.get("go_blockers") or ["missing manual evidence"])
        repo = _fresh_repo_from_row(row)
        issue_number = _fresh_claim_issue_number(row)
        lines.extend(
            [
                "",
                f"{index}. {reference}",
                f"   URL: {row.get('url') or 'no-url'}",
                f"   USD: {row.get('funding_display') or 'unknown'}",
                f"   Age: {float(row['age_hours']):.1f}h via {row['age_basis']}",
                f"   Needs: {blockers}",
                (
                    "   GitHub recheck: "
                    f"gh issue view {shlex.quote(issue_number)} --repo {shlex.quote(repo)} "
                    "--json state,assignees,comments,labels,updatedAt"
                ),
                (
                    "   Local follow-up: "
                    f"{_fresh_readonly_recheck_command(payload, row, 'needs_review')}"
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_claim_packet(payload: dict[str, Any]) -> str:
    rows = [row for row in payload["fresh"] if row.get("solver_status") == "go_candidate"]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        issue_number = _fresh_claim_issue_number(row)
        repo = _fresh_repo_from_row(row)
        candidates.append(
            {
                "reference": row.get("reference") or row.get("url") or "unknown",
                "url": row.get("url"),
                "repository": repo,
                "issue_number": issue_number,
                "funding_display": row.get("funding_display"),
                "age_hours": row.get("age_hours"),
                "age_basis": row.get("age_basis"),
                "attempt_count": row.get("attempt_count"),
                "assignee_count": row.get("assignee_count", 0),
                "go_blockers": row.get("go_blockers") or [],
                "next_action": row.get("next_action") or "prepare_fix_and_claim_pr",
                "readonly_recheck_command": (
                    "gh issue view "
                    f"{shlex.quote(issue_number)} --repo {shlex.quote(repo)} "
                    "--json state,assignees,comments,labels,updatedAt"
                ),
                "local_filter_command": _fresh_claim_recheck_command(payload, row),
                "claim_instruction": (
                    f"Add `/claim #{issue_number}` in the PR only after the branch, "
                    "minimal fix, and target tests are ready."
                ),
            }
        )
    packet = {
        "schema_version": "patchrail.funded_issues.claim_packet.v1",
        "read_only": True,
        "blocked_actions": [
            "automatic_pull_requests",
            "automatic_claim_comments",
            "github_writes",
        ],
        "store_path": payload.get("store_path"),
        "window_hours": payload.get("window_hours"),
        "next_safe_action": payload.get("next_safe_action"),
        "go_count": len(candidates),
        "candidates": candidates,
    }
    return _json_dump(packet)


def _fresh_branch_slug(row: dict[str, Any]) -> str:
    reference = str(row.get("reference") or row.get("url") or "funded-issue").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", reference).strip("-")
    return (slug or "funded-issue")[:64].strip("-")


def _render_funded_issues_fresh_solver_brief(payload: dict[str, Any]) -> str:
    rows = [row for row in payload["fresh"] if row.get("solver_status") == "go_candidate"]
    lines = [
        "# PatchRail funded-issues solver brief",
        "",
        "- Mode: local read-only preparation; no GitHub writes.",
        f"- Window: `{payload['window_hours']}h`",
        f"- GO candidates: `{len(rows)}`",
        f"- Next safe action: `{payload.get('next_safe_action', 'unknown')}`",
    ]
    if not rows:
        lines.extend(
            [
                "",
                "No claim-safe solver candidate is available in the current fresh window.",
            ]
        )
        return "\n".join(lines) + "\n"

    for index, row in enumerate(rows, start=1):
        repo = _fresh_repo_from_row(row)
        issue_number = _fresh_claim_issue_number(row)
        branch = f"patchrail/{_fresh_branch_slug(row)}"
        title = str(row.get("title") or "").strip()
        attempts = row.get("attempt_count")
        attempts_text = "n/a" if attempts is None else str(attempts)
        lines.extend(
            [
                "",
                f"## Candidate {index}: {row.get('reference') or row.get('url') or 'unknown'}",
                "",
                f"- URL: {row.get('url') or 'no-url'}",
                *([f"- Title: {title}"] if title else []),
                f"- Repo: `{repo}`",
                f"- Issue: `#{issue_number}`",
                f"- Funding: `{row.get('funding_display') or 'unknown'}`",
                f"- Age: `{float(row['age_hours']):.1f}h via {row['age_basis']}`",
                f"- Attempts: `{attempts_text}`",
                f"- Assignees: `{row.get('assignee_count', 0)}`",
                f"- Branch: `{branch}`",
                "",
                "### Required local checks before PR",
                "",
                (
                    "1. Re-open the issue and confirm no assignee, reservation, maintainer "
                    "stop signal, or newer competing PR."
                ),
                "2. Inspect the failing path and implement the smallest fix.",
                "3. Run the repo's targeted tests first, then the relevant full suite.",
                "4. Open a PR only after local checks pass; add `/claim` only in the ready PR.",
                "",
                "### Read-only commands",
                "",
                "```bash",
                (
                    f"gh issue view {shlex.quote(issue_number)} --repo {shlex.quote(repo)} "
                    "--json state,assignees,comments,labels,updatedAt"
                ),
                _fresh_claim_recheck_command(payload, row),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "Boundary: no automatic PR, claim comment, issue comment, or maintainer contact.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_claim_checklist(payload: dict[str, Any]) -> str:
    rows = [row for row in payload["fresh"] if row.get("solver_status") == "go_candidate"]
    lines = [
        "PatchRail funded-issues claim checklist",
        (f"Window: {payload['window_hours']}h  Fresh: {payload['fresh_count']}  GO: {len(rows)}"),
        f"Next safe action: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not rows:
        lines.append("No claim-safe solver candidates in the current fresh window.")
        return "\n".join(lines) + "\n"
    for index, row in enumerate(rows, start=1):
        reference = row.get("reference") or row.get("url") or "unknown"
        funding = row.get("funding_display") or "unknown"
        title = str(row.get("title") or "").strip()
        attempts = row.get("attempt_count")
        attempts_text = "n/a" if attempts is None else str(attempts)
        blockers = ", ".join(row.get("go_blockers") or ["none"])
        lines.extend(
            [
                "",
                f"{index}. {reference} - {funding}",
                f"   URL: {row.get('url') or 'no-url'}",
                f"   Age: {float(row['age_hours']):.1f}h via {row['age_basis']}",
                f"   Attempts: {attempts_text}",
                f"   Assignees: {row.get('assignee_count', 0)}",
                f"   GO blockers: {blockers}",
                f"   Action code: {row.get('next_action', 'prepare_fix_and_claim_pr')}",
                f"   Recheck command: {_fresh_claim_recheck_command(payload, row)}",
                "   Claim gate:",
                "   - Re-open issue and confirm no assignee, no reservation, no maintainer stop signal.",
                "   - Create a focused branch, implement the minimal fix, and run the target tests.",
                "   - Open the PR only with passing local checks and a concise technical description.",
                (
                    f"   - Add `/claim #{_fresh_claim_issue_number(row)}` in the PR only "
                    "after the PR is ready."
                ),
            ]
        )
        if title:
            lines.append(f"   Title: {title}")
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_action_queue(payload: dict[str, Any]) -> str:
    rows = list(payload["fresh"])
    go_rows = [row for row in rows if row.get("solver_status") == "go_candidate"]
    lines = [
        "PatchRail funded-issues action queue",
        (
            f"Window: {payload['window_hours']}h  Fresh: {payload['fresh_count']}  "
            f"GO: {len(go_rows)}"
        ),
        f"Next safe action: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not rows:
        lines.append("Next: wait for a fresh funded issue; no local action is safe.")
        return "\n".join(lines) + "\n"
    for index, row in enumerate(rows, start=1):
        reference = row.get("reference") or row.get("url") or "unknown"
        status = row.get("solver_status", "needs_review")
        blockers = row.get("go_blockers") or []
        title = str(row.get("title") or "").strip()
        action_code = row.get("next_action")
        if status == "go_candidate":
            next_action = (
                "prepare branch + minimal fix + target tests; open PR only after checks pass"
            )
        elif status == "needs_review":
            next_action = "manual recheck before coding: " + ", ".join(
                blockers or ["missing current issue evidence"]
            )
        else:
            next_action = "skip: " + ", ".join(blockers or ["not solver-safe"])
        if action_code:
            next_action = f"{next_action} (code: {action_code})"
        lines.extend(
            [
                f"{index}. {status}: {reference}",
                f"   URL: {row.get('url') or 'no-url'}",
                f"   USD: {row.get('funding_display') or 'unknown'}",
                f"   Age: {float(row['age_hours']):.1f}h via {row['age_basis']}",
                f"   Next: {next_action}",
            ]
        )
        if title:
            lines.append(f"   Title: {title}")
    return "\n".join(lines) + "\n"


def _render_funded_issues_fresh_operator_brief(payload: dict[str, Any]) -> str:
    rows = list(payload["fresh"])
    go_rows = [row for row in rows if row.get("solver_status") == "go_candidate"]
    review_rows = [row for row in rows if row.get("solver_status") == "needs_review"]
    skip_rows = [row for row in rows if row.get("solver_status") == "no_go"]
    lines = [
        "PatchRail funded-issues operator brief",
        (
            f"Window: {payload['window_hours']}h  Fresh: {payload['fresh_count']}  "
            f"GO: {len(go_rows)}  Recheck: {len(review_rows)}  Skip: {len(skip_rows)}"
        ),
        f"NEXT_SAFE_ACTION: {payload.get('next_safe_action', 'unknown')}",
    ]
    if not rows:
        lines.extend(
            [
                "Reason: no tracked bounty entered the current window.",
            ]
        )
        return "\n".join(lines) + "\n"

    if go_rows:
        lines.append("")
        lines.append("CLAIM_READY")
        for row in go_rows:
            title = str(row.get("title") or "").strip()
            lines.extend(
                [
                    f"- {row.get('reference') or row.get('url') or 'unknown'}",
                    f"  URL: {row.get('url') or 'no-url'}",
                    f"  USD: {row.get('funding_display') or 'unknown'}",
                    f"  Age: {float(row['age_hours']):.1f}h via {row['age_basis']}",
                    f"  Recheck: {_fresh_claim_recheck_command(payload, row)}",
                    "  Next: branch, minimal fix, target tests, PR, then /claim.",
                ]
            )
            if title:
                lines.append(f"  Title: {title}")

    if review_rows:
        lines.append("")
        lines.append("RECHECK_ONLY")
        for row in review_rows:
            blockers = ", ".join(row.get("go_blockers") or ["missing_current_issue_evidence"])
            lines.extend(
                [
                    f"- {row.get('reference') or row.get('url') or 'unknown'}",
                    f"  URL: {row.get('url') or 'no-url'}",
                    f"  Needs: {blockers}",
                    f"  Code: {row.get('next_action')}",
                ]
            )

    if skip_rows:
        lines.append("")
        lines.append("SKIP")
        for row in skip_rows:
            blockers = ", ".join(row.get("go_blockers") or ["not_solver_safe"])
            lines.append(f"- {row.get('reference') or row.get('url') or 'unknown'}: {blockers}")

    lines.extend(
        [
            "",
            "Boundary: local read-only triage only; no claim, comment, PR, or maintainer contact.",
        ]
    )
    return "\n".join(lines) + "\n"


def _funded_issues_fresh(args: argparse.Namespace) -> int:
    now = args.now or _now_iso()
    solver_status = args.solver_status
    if args.go_only:
        if solver_status not in (None, "go_candidate"):
            print("--go-only cannot be combined with a non-GO --solver-status", file=sys.stderr)
            return 1
        solver_status = "go_candidate"
    try:
        solver_allowlist = _apply_fresh_quality_profile(args)
        store = load_store(args.store)
        orgs = list(args.orgs or [])
        if solver_allowlist is not None:
            orgs.extend(_load_solver_allowlist_orgs(solver_allowlist))
        payload = fresh_issues(
            store,
            now,
            hours=args.hours,
            orgs=orgs or None,
            include_closed=args.include_closed,
            solver_status=solver_status,
            sort_by=args.sort,
            max_rows=args.max_rows,
            min_usd=args.min_usd,
            max_usd=args.max_usd,
            max_attempts=args.max_attempts,
            max_assignees=args.max_assignees,
            min_age_minutes=args.min_age_minutes,
            max_updated_age_hours=args.max_updated_age_hours,
            require_tests_signal=args.require_tests_signal,
        )
        payload["store_path"] = str(args.store)
        payload["quality_profile"] = args.quality_profile
        if solver_allowlist is not None:
            payload["solver_allowlist_path"] = str(solver_allowlist)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid funded issue store: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "csv":
        text = _render_funded_issues_fresh_csv(payload)
    elif args.format == "jsonl":
        text = _render_funded_issues_fresh_jsonl(payload)
    elif args.format == "urls":
        text = _render_funded_issues_fresh_urls(payload)
    elif args.format == "env":
        text = _render_funded_issues_fresh_env(payload)
    elif args.format == "signal":
        text = _render_funded_issues_fresh_signal(payload)
    elif args.format == "digest":
        text = _render_funded_issues_fresh_digest(payload)
    elif args.format == "one-line":
        text = _render_funded_issues_fresh_one_line(payload)
    elif args.format == "github-annotations":
        text = _render_funded_issues_fresh_github_annotations(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_fresh_markdown(payload)
    elif args.format == "shortlist-note":
        text = _render_funded_issues_fresh_shortlist_note(payload)
    elif args.format == "go-list":
        text = _render_funded_issues_fresh_go_list(payload)
    elif args.format == "claim-checklist":
        text = _render_funded_issues_fresh_claim_checklist(payload)
    elif args.format == "claim-packet":
        text = _render_funded_issues_fresh_claim_packet(payload)
    elif args.format == "solver-brief":
        text = _render_funded_issues_fresh_solver_brief(payload)
    elif args.format == "action-queue":
        text = _render_funded_issues_fresh_action_queue(payload)
    elif args.format == "operator-brief":
        text = _render_funded_issues_fresh_operator_brief(payload)
    elif args.format == "recheck-commands":
        text = _render_funded_issues_fresh_recheck_commands(payload)
    elif args.format == "review-watch":
        text = _render_funded_issues_fresh_review_watch(payload)
    else:
        text = _render_funded_issues_fresh_text(payload)
    _write_or_print(text, args.out)
    if args.exit_code_on_go and payload["solver_counts"].get("go_candidate", 0):
        return 2
    return 0


def _render_funded_issues_algora_board_text(payload: dict[str, Any]) -> str:
    lines = [
        "PatchRail Algora board import (local file, read-only)",
        f"Org: {payload['org']}  Board: {payload['source_url']}",
        (
            f"Open on board: {payload['open_count']}  "
            f"Visible rows parsed: {payload['visible_rows']}  "
            f"Visible USD: {payload['visible_usd_total']}"
        ),
    ]
    if payload["open_count"] is not None and payload["visible_rows"] < payload["open_count"]:
        lines.append(
            "Note: the saved page renders only the first rows; "
            f"{payload['open_count'] - payload['visible_rows']} open bounties are not visible."
        )
    for issue in payload["issues"]:
        lines.append(
            f"  - {issue['reference']}: {issue['funding']['display']} "
            f"(attempts: {issue['attempt_count']}, age: {issue['posted']['text'] or 'unknown'})"
        )
    store = payload.get("store")
    if store:
        summary = store["summary"]
        lines.append(
            f"Store {store['path']}: added {summary['added']}, updated {summary['updated']}, "
            f"unchanged {summary['unchanged']}, blocked {summary['blocked']}, "
            f"purged {store['purged_blocklisted']}, total {store['total_entries']}"
        )
    return "\n".join(lines) + "\n"


def _render_funded_issues_algora_board_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# PatchRail Algora Board Import",
        "",
        f"- Org: `{payload['org']}`",
        f"- Board: {payload['source_url']}",
        f"- Open bounties on board: `{payload['open_count']}`",
        f"- Visible rows parsed: `{payload['visible_rows']}`",
        f"- Visible USD total: `{payload['visible_usd_total']}`",
        f"- Read-only: `{payload['read_only']}`",
        "",
        "| Issue | USD | Attempts | Age | Score |",
        "|---|---|---|---|---|",
    ]
    for issue in payload["issues"]:
        lines.append(
            f"| [{_escape_markdown_cell(issue['reference'])}]({issue['url']}) "
            f"| {issue['funding']['display']} "
            f"| {issue['attempt_count']} "
            f"| {issue['posted']['text'] or 'unknown'} "
            f"| {issue['score']} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            (
                "This command parses a locally saved copy of a public Algora bounty board. "
                "It does not fetch URLs, claim rewards, post comments, open pull requests, "
                "or contact maintainers."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _funded_issues_import_algora_board(args: argparse.Namespace) -> int:
    now = args.now or _now_iso()
    try:
        html = args.html.read_text(encoding="utf-8")
        board = parse_board_html(html, args.org)
        records = board_issue_records(board, retrieved_at=now)
        payload = board_payload(board, records, retrieved_at=now)
        if args.store is not None:
            store = load_store(args.store)
            purge = purge_blocklisted_entries(store)
            summary = merge_into_store(store, records, now)
            save_store(args.store, store)
            payload["store"] = {
                "path": str(args.store),
                "purged_blocklisted": purge["removed"],
                "summary": summary.to_dict(),
                "total_entries": len(store["entries"]),
            }
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid Algora board source: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = _json_dump(payload)
    elif args.format == "markdown":
        text = _render_funded_issues_algora_board_markdown(payload)
    else:
        text = _render_funded_issues_algora_board_text(payload)
    _write_or_print(text, args.out)
    return 0


def _normalize_recheck_observation(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one recheck observation, accepting native or GitHub API shapes.

    A native observation already uses ``url`` / ``state`` / ``updated_at`` /
    ``closed_at`` / ``assignee_count`` / ``comments``. A GitHub API issue object
    exposes ``html_url`` (or ``url``), ``state`` (open|closed), ``updated_at``,
    ``closed_at``, ``comments`` and an ``assignees`` list -- those are mapped to
    the native vocabulary so both inputs feed the same store function.
    """

    url = raw.get("url") or raw.get("html_url")
    observation: dict[str, Any] = {
        "url": str(url) if url else None,
        "state": raw.get("state"),
    }
    if raw.get("updated_at") is not None:
        observation["updated_at"] = raw["updated_at"]
    if raw.get("closed_at") is not None:
        observation["closed_at"] = raw["closed_at"]
    if raw.get("comments") is not None:
        observation["comments"] = raw["comments"]
    if raw.get("assignee_count") is not None:
        observation["assignee_count"] = raw["assignee_count"]
    elif isinstance(raw.get("assignees"), list):
        observation["assignee_count"] = len(raw["assignees"])
    return observation


def _load_recheck_observations(source: Path) -> list[dict[str, Any]]:
    """Load and normalize recheck observations from a local JSON file.

    Accepts a bare list of observations, an object ``{"observations": [...]}``,
    or a list of GitHub API issue objects. Performs zero network calls.
    """

    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise ValueError('observations object must contain an "observations" list')
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("recheck input must be a list or an observations object")

    observations: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each recheck observation must be an object")
        observations.append(_normalize_recheck_observation(row))
    return observations


def _render_funded_issues_apply_recheck_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    transitions = summary["transitions"]
    lines = [
        "PatchRail funded-issues tracker recheck",
        f"Store: {payload['store']}",
        f"Now: {payload['now']}  Stale after: {payload['stale_after_days']}d"
        + ("  (dry-run)" if payload["dry_run"] else ""),
        f"Checked: {summary['checked']}  Matched: {summary['matched']}  "
        f"Unmatched: {summary['unmatched']}",
        f"To closed: {transitions['to_closed']}  To stale: {transitions['to_stale']}  "
        f"To active: {transitions['to_active']}  Unchanged: {summary['unchanged']}",
    ]
    for transition in summary["transition_log"]:
        lines.append(f"  - {transition['url']}: {transition['from']} -> {transition['state']}")
    return "\n".join(lines) + "\n"


def _funded_issues_apply_recheck(args: argparse.Namespace) -> int:
    now = args.now or _now_iso()
    try:
        observations = _load_recheck_observations(args.input)
        store = load_store(args.store)
        summary = apply_recheck_to_store(
            store, observations, now, stale_after_days=args.stale_after_days
        )
        if not args.dry_run:
            save_store(args.store, store)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid recheck input: {exc}", file=sys.stderr)
        return 1
    safe = empty_store()
    payload = {
        "schema_version": "patchrail.funded_issues.recheck_summary.v1",
        "source_schema_version": safe["source_schema_version"],
        "read_only": True,
        "blocked_actions": list(safe["blocked_actions"]),
        "requirements": dict(safe["requirements"]),
        "store": str(args.store),
        "input": str(args.input),
        "now": now,
        "stale_after_days": args.stale_after_days,
        "dry_run": bool(args.dry_run),
        "total_entries": len(store["entries"]),
        "summary": summary.to_dict(),
    }
    if args.format == "json":
        text = _json_dump(payload)
    else:
        text = _render_funded_issues_apply_recheck_text(payload)
    _write_or_print(text, args.out)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `funded-issues` subcommand tree to the root parser."""
    funded = subparsers.add_parser(
        "funded-issues",
        help=(
            "Experimental: read-only funded-issue discovery. Human-gated. "
            "See docs/funded-issues-ethics.md."
        ),
        description=(
            "Experimental: read-only funded-issue discovery. Human-gated. "
            "See docs/funded-issues-ethics.md."
        ),
    )
    funded_subparsers = funded.add_subparsers(dest="funded_issues_command", required=True)

    funded_validate = funded_subparsers.add_parser(
        "validate",
        help="Validate a local funded issue dataset before using it as tracker evidence.",
    )
    funded_validate.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_validate.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when review warnings are present.",
    )
    funded_validate.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    funded_validate.add_argument("--out", type=Path, help="Optional output path.")
    funded_validate.set_defaults(func=_funded_issues_validate)

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
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before output. Read-only.",
    )
    funded_list.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_list.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_list.add_argument(
        "--format",
        choices=["csv", "json", "jsonl", "markdown", "text"],
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

    funded_import = funded_subparsers.add_parser(
        "import",
        help="Normalize a local provider export into PatchRail's read-only funded issue schema.",
    )
    funded_import.add_argument(
        "--provider",
        required=True,
        choices=SUPPORTED_PROVIDERS,
        help="Provider export format to normalize.",
    )
    funded_import.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Local JSON export file. PatchRail does not fetch provider APIs.",
    )
    funded_import.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="json",
        help="Output format.",
    )
    funded_import.add_argument("--out", type=Path, help="Optional output path.")
    funded_import.set_defaults(func=_funded_issues_import)

    funded_algora_board = funded_subparsers.add_parser(
        "import-algora-board",
        help="Parse a locally saved Algora org bounty-board page into funded issues "
        "with funder-stated USD amounts, optionally merging them into a tracker store.",
    )
    funded_algora_board.add_argument(
        "--html",
        required=True,
        type=Path,
        help="Locally saved copy of https://algora.io/<org>/bounties. "
        "PatchRail does not fetch the page itself.",
    )
    funded_algora_board.add_argument(
        "--org",
        required=True,
        help="Algora organization handle the page was saved from.",
    )
    funded_algora_board.add_argument(
        "--store",
        type=Path,
        help="Optional local tracker store to merge the parsed bounties into. "
        "Created when absent. PatchRail never writes to third parties.",
    )
    funded_algora_board.add_argument(
        "--now",
        help="ISO-8601 UTC timestamp to record as retrieval/merge time. "
        "Defaults to the local clock.",
    )
    funded_algora_board.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="text",
        help="Output format.",
    )
    funded_algora_board.add_argument("--out", type=Path, help="Optional output path.")
    funded_algora_board.set_defaults(func=_funded_issues_import_algora_board)

    funded_report = funded_subparsers.add_parser(
        "report",
        help="Summarize local funded issue coverage and no-go moat metrics.",
    )
    funded_report.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_report.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_report.add_argument("--platform", help="Filter by funding platform.")
    funded_report.add_argument("--language", help="Filter by repository language.")
    funded_report.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_report.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before reporting. Read-only.",
    )
    funded_report.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_report.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_report.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_report.add_argument("--out", type=Path, help="Optional output path.")
    funded_report.set_defaults(func=_funded_issues_report)

    funded_score = funded_subparsers.add_parser(
        "score",
        help="Score local funded issue readiness with read-only reason codes.",
    )
    funded_score.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_score.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_score.add_argument("--platform", help="Filter by funding platform.")
    funded_score.add_argument("--language", help="Filter by repository language.")
    funded_score.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_score.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before scoring. Read-only.",
    )
    funded_score.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_score.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_score.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="json",
        help="Output format.",
    )
    funded_score.add_argument("--out", type=Path, help="Optional output path.")
    funded_score.set_defaults(func=_funded_issues_score)

    funded_shortlist = funded_subparsers.add_parser(
        "shortlist",
        help="Build a local read-only shortlist artifact with no-go evidence.",
    )
    funded_shortlist.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_shortlist.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_shortlist.add_argument("--platform", help="Filter by funding platform.")
    funded_shortlist.add_argument("--language", help="Filter by repository language.")
    funded_shortlist.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_shortlist.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before shortlisting. Read-only.",
    )
    funded_shortlist.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_shortlist.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_shortlist.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum shortlist candidate rows to include.",
    )
    funded_shortlist.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_shortlist.add_argument("--out", type=Path, help="Optional output path.")
    funded_shortlist.set_defaults(func=_funded_issues_shortlist)

    funded_client_report = funded_subparsers.add_parser(
        "client-report",
        help="Build the client-facing Opportunity Shortlist deliverable (read-only).",
    )
    funded_client_report.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_client_report.add_argument(
        "--client-name",
        required=True,
        help="Client name the report is prepared for.",
    )
    funded_client_report.add_argument(
        "--date",
        required=True,
        help="Report date in ISO format (injected for deterministic output).",
    )
    funded_client_report.add_argument(
        "--prepared-by",
        default="PatchRail Opportunity Desk",
        help="Author line for the report.",
    )
    funded_client_report.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_client_report.add_argument("--platform", help="Filter by funding platform.")
    funded_client_report.add_argument("--language", help="Filter by repository language.")
    funded_client_report.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_client_report.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before shortlisting. Read-only.",
    )
    funded_client_report.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_client_report.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_client_report.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum shortlist candidate rows to include.",
    )
    funded_client_report.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_client_report.add_argument("--out", type=Path, help="Optional output path.")
    funded_client_report.set_defaults(func=_funded_issues_client_report)

    funded_recheck_queue = funded_subparsers.add_parser(
        "recheck-queue",
        help="Build a local read-only recheck queue for funded issue tracker maintenance.",
    )
    funded_recheck_queue.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_recheck_queue.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_recheck_queue.add_argument("--platform", help="Filter by funding platform.")
    funded_recheck_queue.add_argument("--language", help="Filter by repository language.")
    funded_recheck_queue.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_recheck_queue.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before queueing. Read-only.",
    )
    funded_recheck_queue.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_recheck_queue.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_recheck_queue.add_argument(
        "--max-rows",
        type=int,
        help="Limit active recheck rows after priority sorting. Must be at least 1.",
    )
    funded_recheck_queue.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_recheck_queue.add_argument("--out", type=Path, help="Optional output path.")
    funded_recheck_queue.set_defaults(func=_funded_issues_recheck_queue)

    funded_cash_actions = funded_subparsers.add_parser(
        "cash-actions",
        help="Build an internal read-only next-action queue for funded-issues review.",
    )
    funded_cash_actions.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_cash_actions.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_cash_actions.add_argument("--platform", help="Filter by funding platform.")
    funded_cash_actions.add_argument("--language", help="Filter by repository language.")
    funded_cash_actions.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_cash_actions.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before action planning. Read-only.",
    )
    funded_cash_actions.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_cash_actions.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_cash_actions.add_argument(
        "--max-actions",
        type=int,
        help="Limit internal action rows after priority sorting. Must be at least 1.",
    )
    funded_cash_actions.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_cash_actions.add_argument("--out", type=Path, help="Optional output path.")
    funded_cash_actions.set_defaults(func=_funded_issues_cash_actions)

    funded_fulfillment_packet = funded_subparsers.add_parser(
        "fulfillment-packet",
        help="Build an internal read-only fulfillment packet for paid delivery operations.",
    )
    funded_fulfillment_packet.add_argument(
        "--source",
        type=Path,
        help="Local JSON source. Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_fulfillment_packet.add_argument(
        "--include-risky",
        action="store_true",
        help="Include high-risk issues in local output. Still read-only.",
    )
    funded_fulfillment_packet.add_argument("--platform", help="Filter by funding platform.")
    funded_fulfillment_packet.add_argument("--language", help="Filter by repository language.")
    funded_fulfillment_packet.add_argument(
        "--min-usd", type=float, help="Filter to USD-funded issues at least this amount."
    )
    funded_fulfillment_packet.add_argument(
        "--profile",
        type=Path,
        help="Local client profile JSON used to reduce rows before packet planning. Read-only.",
    )
    funded_fulfillment_packet.add_argument(
        "--opportunity-state",
        choices=sorted(VALID_OPPORTUNITY_STATES),
        help="Filter by normalized opportunity state.",
    )
    funded_fulfillment_packet.add_argument(
        "--risk-level",
        choices=sorted(VALID_RISK_LEVELS),
        help="Filter by normalized local risk level.",
    )
    funded_fulfillment_packet.add_argument(
        "--max-items",
        type=int,
        help="Limit internal fulfillment items after priority sorting. Must be at least 1.",
    )
    funded_fulfillment_packet.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_fulfillment_packet.add_argument("--out", type=Path, help="Optional output path.")
    funded_fulfillment_packet.set_defaults(func=_funded_issues_fulfillment_packet)

    funded_competition = funded_subparsers.add_parser(
        "competition",
        help="Score read-only competition / noise-trap pressure for a batch of bounties.",
    )
    funded_competition.add_argument(
        "--source",
        type=Path,
        help=(
            "Local JSON file of public competition observations (list, or an object with an "
            "'observations' list). Defaults to "
            "examples/funded-issues-readonly/competition-observations.json."
        ),
    )
    funded_competition.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_competition.add_argument("--out", type=Path, help="Optional output path.")
    funded_competition.set_defaults(func=_funded_issues_competition)

    funded_payout_effort = funded_subparsers.add_parser(
        "payout-effort",
        help="Score read-only payout-vs-effort for a batch of bounties against a rate floor.",
    )
    funded_payout_effort.add_argument(
        "--source",
        type=Path,
        help=(
            "Local JSON file of payout-effort observations (list, or an object with an "
            "'observations' list). Defaults to "
            "examples/funded-issues-readonly/payout-effort-observations.json."
        ),
    )
    funded_payout_effort.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_payout_effort.add_argument("--out", type=Path, help="Optional output path.")
    funded_payout_effort.set_defaults(func=_funded_issues_payout_effort)

    funded_staleness = funded_subparsers.add_parser(
        "staleness",
        help="Score read-only staleness / liveness for a batch of bounties from age signals.",
    )
    funded_staleness.add_argument(
        "--source",
        type=Path,
        help=(
            "Local JSON file of staleness observations (list, or an object with an "
            "'observations' list). Defaults to "
            "examples/funded-issues-readonly/staleness-observations.json."
        ),
    )
    funded_staleness.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_staleness.add_argument("--out", type=Path, help="Optional output path.")
    funded_staleness.set_defaults(func=_funded_issues_staleness)

    funded_testability = funded_subparsers.add_parser(
        "testability",
        help="Score read-only testability / reproducibility for a batch of bounties.",
    )
    funded_testability.add_argument(
        "--source",
        type=Path,
        help=(
            "Local JSON file of testability observations (list, or an object with an "
            "'observations' list). Defaults to "
            "examples/funded-issues-readonly/testability-observations.json."
        ),
    )
    funded_testability.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="markdown",
        help="Output format.",
    )
    funded_testability.add_argument("--out", type=Path, help="Optional output path.")
    funded_testability.set_defaults(func=_funded_issues_testability)

    funded_track = funded_subparsers.add_parser(
        "track",
        help="Incrementally merge local funded issues into a persistent read-only tracker store.",
    )
    funded_track.add_argument(
        "--store",
        required=True,
        type=Path,
        help="Local JSON store file. Created when absent. PatchRail never writes to third parties.",
    )
    funded_track.add_argument(
        "--input",
        type=Path,
        help="Local JSON source of already-discovered issues. "
        "Defaults to examples/funded-issues-readonly/issues.json.",
    )
    funded_track.add_argument(
        "--now",
        help="ISO-8601 UTC timestamp to record. Defaults to the local clock.",
    )
    funded_track.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    funded_track.add_argument("--out", type=Path, help="Optional output path.")
    funded_track.set_defaults(func=_funded_issues_track)

    funded_track_status = funded_subparsers.add_parser(
        "track-status",
        help="Summarize a persistent read-only funded issue tracker store.",
    )
    funded_track_status.add_argument(
        "--store",
        required=True,
        type=Path,
        help="Local JSON store file written by funded-issues track.",
    )
    funded_track_status.add_argument(
        "--now",
        help="ISO-8601 UTC timestamp used to compute added_24h. Defaults to the local clock.",
    )
    funded_track_status.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    funded_track_status.add_argument("--out", type=Path, help="Optional output path.")
    funded_track_status.set_defaults(func=_funded_issues_track_status)

    funded_fresh = funded_subparsers.add_parser(
        "fresh",
        help="List tracker entries whose bounty was posted/labeled within a recent "
        "window, ordered by freshness. Local read-only; no network.",
    )
    funded_fresh.add_argument(
        "--store",
        required=True,
        type=Path,
        help="Local JSON store file written by funded-issues track.",
    )
    funded_fresh.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Freshness window in hours. Default 48.",
    )
    funded_fresh.add_argument(
        "--org",
        action="append",
        dest="orgs",
        metavar="ORG",
        help="Restrict to this funding org/owner (repeatable). Defaults to all orgs "
        "in the store. Pass the allowlist orgs to cross-reference them.",
    )
    funded_fresh.add_argument(
        "--solver-allowlist",
        type=Path,
        help="Markdown allowlist whose first table column contains org/* or org/repo entries.",
    )
    funded_fresh.add_argument(
        "--quality-profile",
        choices=["solver"],
        help=(
            "Apply a named local quality preset. 'solver' scopes to the solver allowlist "
            "and applies USD 25-300, attempts<=3, min age 10m, updated<=168h, "
            "and public testability-signal filters."
        ),
    )
    funded_fresh.add_argument(
        "--include-closed",
        action="store_true",
        help="Include entries whose tracked state is closed. Off by default.",
    )
    funded_fresh.add_argument(
        "--solver-status",
        choices=["go_candidate", "needs_review", "no_go"],
        help="Restrict fresh rows to one local solver status.",
    )
    funded_fresh.add_argument(
        "--go-only",
        action="store_true",
        help="Shortcut for --solver-status go_candidate; keeps fresh radar output claim-focused.",
    )
    funded_fresh.add_argument(
        "--sort",
        choices=["freshness", "solver"],
        default="freshness",
        help="Sort rows by freshness (default) or by solver status, with GO candidates first.",
    )
    funded_fresh.add_argument(
        "--max-rows",
        type=int,
        help="Maximum fresh rows to return after filtering and sorting.",
    )
    funded_fresh.add_argument(
        "--min-usd",
        type=float,
        help="Only include USD-funded fresh rows at least this amount.",
    )
    funded_fresh.add_argument(
        "--max-usd",
        type=float,
        help="Only include USD-funded fresh rows at most this amount.",
    )
    funded_fresh.add_argument(
        "--max-attempts",
        type=int,
        help=(
            "Only include fresh rows with a known attempt count at or below this value. "
            "Use 3 for solver-lane claim sweeps."
        ),
    )
    funded_fresh.add_argument(
        "--max-assignees",
        type=int,
        help="Only include fresh rows with this many assignees or fewer. Use 0 for claim sweeps.",
    )
    funded_fresh.add_argument(
        "--min-age-minutes",
        type=int,
        help=(
            "Only include fresh rows at least this many minutes old. Use this to avoid "
            "claiming before public issue signals have stabilized."
        ),
    )
    funded_fresh.add_argument(
        "--max-updated-age-hours",
        type=int,
        help=(
            "Only include fresh rows whose public updated_at signal is this many hours old "
            "or newer. Use this to ignore fresh-but-inactive bounty traps."
        ),
    )
    funded_fresh.add_argument(
        "--require-tests-signal",
        action="store_true",
        help=(
            "Only include fresh rows whose public contribution signals mention a reproduction, "
            "test, log, stack trace, expected/actual behavior, or diagnostic path."
        ),
    )
    funded_fresh.add_argument(
        "--now",
        help="ISO-8601 UTC timestamp used to compute freshness. Defaults to the local clock.",
    )
    funded_fresh.add_argument(
        "--format",
        choices=[
            "action-queue",
            "claim-checklist",
            "claim-packet",
            "csv",
            "digest",
            "env",
            "go-list",
            "github-annotations",
            "json",
            "jsonl",
            "markdown",
            "operator-brief",
            "one-line",
            "recheck-commands",
            "review-watch",
            "signal",
            "shortlist-note",
            "solver-brief",
            "text",
            "urls",
        ],
        default="text",
        help="Output format.",
    )
    funded_fresh.add_argument(
        "--exit-code-on-go",
        action="store_true",
        help="Return exit code 2 when the filtered fresh window contains a GO candidate. "
        "Output is still written normally for cron/supervisor parsing.",
    )
    funded_fresh.add_argument("--out", type=Path, help="Optional output path.")
    funded_fresh.set_defaults(func=_funded_issues_fresh)

    funded_apply_recheck = funded_subparsers.add_parser(
        "apply-recheck",
        help="Apply local recheck observations to a tracker store, transitioning states.",
    )
    funded_apply_recheck.add_argument(
        "--store",
        required=True,
        type=Path,
        help="Local JSON store file written by funded-issues track. "
        "PatchRail never writes to third parties.",
    )
    funded_apply_recheck.add_argument(
        "--input",
        required=True,
        type=Path,
        help='Local JSON observations: a list, an {"observations": [...]} object, '
        "or a list of GitHub API issue objects. No network is touched.",
    )
    funded_apply_recheck.add_argument(
        "--now",
        help="ISO-8601 UTC timestamp to record. Defaults to the local clock.",
    )
    funded_apply_recheck.add_argument(
        "--stale-after-days",
        type=int,
        default=45,
        help="Days since updated_at after which an open issue is marked stale. Default 45.",
    )
    funded_apply_recheck.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    funded_apply_recheck.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report transitions without writing the store.",
    )
    funded_apply_recheck.add_argument("--out", type=Path, help="Optional output path.")
    funded_apply_recheck.set_defaults(func=_funded_issues_apply_recheck)
