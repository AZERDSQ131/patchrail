from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


class PatchRailFundedIssuesTests(unittest.TestCase):
    def test_funded_issues_list_is_safe_only_and_read_only_by_default(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.v1")
        self.assertEqual(payload["safe_only"], True)
        self.assertEqual(payload["read_only"], True)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_returned"], 1)
        self.assertEqual(payload["issues"][0]["reference"], "example/project#42")
        self.assertEqual(payload["issues"][0]["risk_level"], "low")
        self.assertEqual(payload["issues"][0]["opportunity_state"], "active")
        self.assertIn("automatic_pull_requests", payload["blocked_actions"])
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_funded_issues_can_show_risky_items_only_when_requested(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--include-risky",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["safe_only"], False)
        self.assertEqual(payload["total_returned"], 2)
        risky = [issue for issue in payload["issues"] if issue["risk_level"] == "high"]
        self.assertEqual(risky[0]["reference"], "example/toolkit#17")
        self.assertEqual(risky[0]["opportunity_state"], "closed")
        self.assertFalse(risky[0]["safe_to_list"])
        self.assertIn("ambiguous_scope", risky[0]["risk_flags"])

    def test_funded_issues_list_exports_safe_only_tracker_csv(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "csv",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = list(csv.DictReader(io.StringIO(proc.stdout)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference"], "example/project#42")
        self.assertEqual(rows[0]["platform"], "polar")
        self.assertEqual(rows[0]["funding_amount"], "250.0")
        self.assertEqual(rows[0]["funding_currency"], "USD")
        self.assertEqual(rows[0]["opportunity_state"], "active")
        self.assertEqual(rows[0]["risk_level"], "low")
        self.assertEqual(rows[0]["safe_to_list"], "true")
        self.assertEqual(rows[0]["read_only"], "true")
        self.assertIn("reproduction included", rows[0]["contribution_signals"])

    def test_funded_issues_list_exports_safe_only_jsonl_for_pipeline_ingest(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "jsonl",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["reference"], "example/project#42")
        self.assertEqual(row["risk_level"], "low")
        self.assertEqual(row["opportunity_state"], "active")
        self.assertEqual(row["read_only"], True)
        self.assertTrue(row["safe_to_list"])
        self.assertIn("automatic_pull_requests", row["blocked_actions"])
        self.assertIn("reproduction included", row["contribution_signals"])

    def test_funded_issues_list_can_filter_by_opportunity_state(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--include-risky",
                "--opportunity-state",
                "closed",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_returned"], 1)
        self.assertEqual(payload["issues"][0]["reference"], "example/toolkit#17")
        self.assertEqual(payload["issues"][0]["opportunity_state"], "closed")
        self.assertFalse(payload["issues"][0]["safe_to_list"])

    def test_funded_issues_list_can_filter_by_risk_level(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--include-risky",
                "--risk-level",
                "high",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_returned"], 1)
        self.assertEqual(payload["issues"][0]["reference"], "example/toolkit#17")
        self.assertEqual(payload["issues"][0]["risk_level"], "high")
        self.assertFalse(payload["issues"][0]["safe_to_list"])

    def test_funded_issues_list_csv_neutralizes_formula_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "formula-title",
                                "platform": "github",
                                "repository": "example/formula",
                                "issue_number": 9,
                                "title": '=IMPORTDATA("https://example.invalid")',
                                "url": "https://github.com/example/formula/issues/9",
                                "funding": {"amount": 100, "currency": "USD"},
                                "language": "python",
                                "labels": ["bug"],
                                "risk_flags": [],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/formula/blob/main/CONTRIBUTING.md"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "list",
                    "--source",
                    str(source),
                    "--format",
                    "csv",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = list(csv.DictReader(io.StringIO(proc.stdout)))
        self.assertEqual(rows[0]["title"], '\'=IMPORTDATA("https://example.invalid")')

    def test_funded_issues_explain_states_ethics_boundary(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "explain",
                "example/project#42",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issue", proc.stdout)
        self.assertIn("Safe to keep in a local funded-maintenance shortlist", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)
        self.assertIn("does not claim rewards", proc.stdout)

    def test_funded_issues_unknown_reference_fails_cleanly(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "explain",
                "example/missing#1",
                "--source",
                "examples/funded-issues-readonly/issues.json",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("Unknown funded issue", proc.stderr)

    def test_funded_issues_import_normalizes_local_provider_export(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "import",
                "--provider",
                "github",
                "--source",
                "examples/funded-issues-readonly/provider-github-export.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.v1")
        self.assertEqual(payload["read_only"], True)
        self.assertEqual(payload["import_source"]["provider"], "github")
        self.assertEqual(payload["import_source"]["local_file_only"], True)
        self.assertEqual(payload["import_source"]["records_loaded"], 2)
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)
        safe_issue = payload["issues"][0]
        self.assertEqual(safe_issue["reference"], "example/project#42")
        self.assertEqual(safe_issue["funding"]["display"], "250 USD")
        self.assertEqual(safe_issue["opportunity_state"], "active")
        self.assertEqual(safe_issue["risk_level"], "low")
        self.assertIn("contribution guidelines linked", safe_issue["contribution_signals"])
        risky_issue = payload["issues"][1]
        self.assertEqual(risky_issue["reference"], "example/toolkit#17")
        self.assertEqual(risky_issue["opportunity_state"], "closed")
        self.assertEqual(risky_issue["risk_level"], "high")
        self.assertIn("closed_or_inactive", risky_issue["risk_flags"])
        self.assertIn("ambiguous_scope", risky_issue["risk_flags"])
        self.assertIn("automatic_issue_comments", payload["blocked_actions"])

    def test_imported_provider_export_can_feed_safe_only_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalized = Path(tmp) / "funded-issues.json"
            import_proc = run_patchrail(
                [
                    "funded-issues",
                    "import",
                    "--provider",
                    "github",
                    "--source",
                    "examples/funded-issues-readonly/provider-github-export.json",
                    "--out",
                    str(normalized),
                ]
            )
            self.assertEqual(import_proc.returncode, 0, import_proc.stderr)

            list_proc = run_patchrail(
                [
                    "funded-issues",
                    "list",
                    "--source",
                    str(normalized),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        payload = json.loads(list_proc.stdout)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_returned"], 1)
        self.assertEqual(payload["issues"][0]["reference"], "example/project#42")

    def test_funded_issues_validate_passes_clean_local_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clean-funded-issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "clean-issue",
                                "platform": "polar",
                                "repository": "example/clean",
                                "issue_number": 12,
                                "title": "Fix reproducible CLI regression",
                                "url": "https://github.com/example/clean/issues/12",
                                "funding": {"amount": 250, "currency": "USD"},
                                "language": "python",
                                "opportunity_state": "active",
                                "labels": ["bug"],
                                "contribution_signals": ["reproduction included"],
                                "risk_flags": [],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/clean/blob/main/CONTRIBUTING.md"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                ["funded-issues", "validate", "--source", str(source), "--format", "json"]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.validation.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["warning_count"], 0)
        self.assertEqual(payload["counts"]["low_risk"], 1)
        self.assertEqual(payload["counts"]["active"], 1)
        self.assertEqual(payload["counts"]["stale"], 0)
        self.assertEqual(payload["counts"]["closed"], 0)
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_funded_issues_validate_warns_on_review_gaps_without_strict_failure(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "validate",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "needs_review")
        self.assertGreater(payload["warning_count"], 0)
        self.assertIn("example/toolkit#17", payload["warnings"]["high_risk"])
        self.assertIn("example/toolkit#17", payload["warnings"]["missing_contribution_guidelines"])
        self.assertIn("example/toolkit#17", payload["warnings"]["stale_or_closed"])
        self.assertIn("automatic_claims", payload["blocked_actions"])
        self.assertIn("read-only", payload["boundary"])

    def test_funded_issues_validate_strict_fails_on_review_warnings(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "validate",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--strict",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["strict"])
        self.assertEqual(payload["status"], "needs_review")
        self.assertGreater(payload["warning_count"], 0)

    def test_funded_issues_validate_returns_structured_invalid_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "invalid-funded-issues.json"
            source.write_text(
                json.dumps({"schema_version": "wrong.version", "issues": []}),
                encoding="utf-8",
            )

            proc = run_patchrail(
                ["funded-issues", "validate", "--source", str(source), "--format", "json"]
            )

        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["total_loaded"], 0)
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertIn("patchrail.funded_issues.v1", payload["errors"][0])

    def test_funded_issues_report_summarizes_coverage_and_no_go_moat(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "report",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.report.v1")
        self.assertEqual(payload["read_only"], True)
        self.assertEqual(payload["totals"]["loaded"], 2)
        self.assertEqual(payload["totals"]["in_scope"], 2)
        self.assertEqual(payload["totals"]["safe_to_list"], 1)
        self.assertEqual(payload["totals"]["high_risk"], 1)
        self.assertEqual(payload["breakdown"]["risk_levels"], {"high": 1, "low": 1})
        self.assertEqual(payload["breakdown"]["platforms"], {"algora": 1, "polar": 1})
        self.assertEqual(payload["breakdown"]["opportunity_states"], {"active": 1, "closed": 1})
        self.assertEqual(payload["no_go_moat"]["high_risk_or_excluded"], 1)
        self.assertEqual(payload["no_go_moat"]["ambiguous_scope"], 1)
        self.assertEqual(payload["no_go_moat"]["spam_attractive"], 1)
        self.assertEqual(payload["no_go_moat"]["stale_or_closed"], 1)
        self.assertEqual(payload["decision_summary"]["candidate_rows"], 1)
        self.assertEqual(payload["decision_summary"]["no_go_rows"], 1)
        self.assertEqual(payload["decision_summary"]["verification_needed"], 0)
        self.assertEqual(payload["decision_summary"]["authorization_needed"], 0)
        self.assertEqual(payload["decision_summary"]["gate_counts"]["go_after_recheck"], 1)
        self.assertEqual(payload["decision_summary"]["gate_counts"]["no_go"], 1)
        self.assertIn(
            "Review go-after-recheck",
            payload["decision_summary"]["recommended_batch_action"],
        )
        self.assertIn("do not claim", payload["decision_summary"]["safety_boundary"])
        self.assertEqual(payload["delivery_budget"]["suggested_package"], "mini_diagnostic")
        self.assertEqual(payload["delivery_budget"]["estimated_review_minutes"], 13)
        self.assertEqual(payload["delivery_budget"]["estimated_review_hours"], 0.22)
        self.assertEqual(payload["delivery_budget"]["max_paid_hours"], 3)
        self.assertTrue(payload["delivery_budget"]["within_margin_budget"])
        self.assertEqual(
            payload["delivery_budget"]["analysis_rows"],
            {
                "l1_state_and_noise_review": 1,
                "l2_scope_and_readiness_review": 1,
                "l3_deep_dive_deferred": 0,
            },
        )
        self.assertIn("paid scope", payload["delivery_budget"]["boundary"])
        delivery_pack = payload["delivery_pack"]
        self.assertEqual(delivery_pack["suggested_package"], "mini_diagnostic")
        self.assertEqual(
            delivery_pack["phase_counts"],
            {
                "l1_state_and_noise_review": 1,
                "l2_shortlist_readiness_review": 1,
                "l3_deep_dive_deferred": 0,
            },
        )
        self.assertEqual(
            delivery_pack["handoff"]["candidate_references"],
            ["example/project#42"],
        )
        self.assertEqual(
            delivery_pack["handoff"]["no_go_references"],
            ["example/toolkit#17"],
        )
        self.assertIn("paid decision support", delivery_pack["boundary"])
        source_quality = payload["source_quality"]
        self.assertEqual(
            source_quality["summary"],
            {
                "source_count": 2,
                "total_rows": 2,
                "candidate_rows": 1,
                "no_go_rows": 1,
                "candidate_source_count": 1,
                "no_go_only_source_count": 1,
                "funding_verification_needed": 0,
                "authorization_needed": 0,
                "status": "candidate_sources_available",
                "next_tracker_action": (
                    "Run read-only public-state recheck on candidate sources before paid "
                    "shortlist use."
                ),
                "boundary": (
                    "Source summary is local tracker evidence only. It does not authorize "
                    "scraping, claims, comments, maintainer contact, pull requests, or "
                    "payout/merge guarantees."
                ),
            },
        )
        self.assertEqual(source_quality["sources"]["polar"]["total_rows"], 1)
        self.assertEqual(source_quality["sources"]["polar"]["candidate_rows"], 1)
        self.assertEqual(source_quality["sources"]["polar"]["no_go_rows"], 0)
        self.assertEqual(source_quality["sources"]["polar"]["safe_to_list"], 1)
        self.assertEqual(source_quality["sources"]["polar"]["average_score"], 99)
        self.assertEqual(source_quality["sources"]["polar"]["usable_signal_ratio"], 1)
        self.assertEqual(source_quality["sources"]["algora"]["total_rows"], 1)
        self.assertEqual(source_quality["sources"]["algora"]["candidate_rows"], 0)
        self.assertEqual(source_quality["sources"]["algora"]["no_go_rows"], 1)
        self.assertEqual(source_quality["sources"]["algora"]["safe_to_list"], 0)
        self.assertEqual(source_quality["sources"]["algora"]["average_score"], 0)
        self.assertEqual(source_quality["sources"]["algora"]["usable_signal_ratio"], 0)
        self.assertIn("no-go moat evidence", source_quality["sources"]["algora"]["recommended_use"])
        self.assertIn("read-only benchmarking", source_quality["boundary"])
        recheck_plan = payload["recheck_plan"]
        self.assertEqual(recheck_plan["total_rows"], 2)
        self.assertEqual(recheck_plan["recheck_rows"], 1)
        self.assertEqual(recheck_plan["no_go_rows"], 1)
        self.assertEqual(recheck_plan["priority_counts"], {"high": 1})
        self.assertEqual(
            recheck_plan["action_counts"],
            {"archive_as_no_go_evidence": 1, "recheck_public_issue_state": 1},
        )
        self.assertEqual(recheck_plan["next_rows"][0]["reference"], "example/project#42")
        self.assertEqual(recheck_plan["next_rows"][0]["priority"], "high")
        self.assertEqual(recheck_plan["next_rows"][0]["action"], "recheck_public_issue_state")
        self.assertIn("read-only tracker triage", recheck_plan["boundary"])
        client_fit_summary = payload["client_fit_summary"]
        self.assertIsNone(client_fit_summary["profile_name"])
        self.assertEqual(client_fit_summary["status"], "no_profile")
        self.assertEqual(client_fit_summary["total_rows"], 2)
        self.assertEqual(client_fit_summary["matching_rows"], 2)
        self.assertEqual(client_fit_summary["excluded_rows"], 0)
        self.assertEqual(client_fit_summary["gap_counts"], {})
        self.assertIn("read-only client profile", client_fit_summary["recommended_action"])
        self.assertIn("does not authorize claiming", client_fit_summary["boundary"])
        intake_followup = payload["intake_followup"]
        self.assertEqual(intake_followup["status"], "needs_buyer_intake")
        self.assertEqual(intake_followup["suggested_package"], "mini_diagnostic")
        self.assertEqual(intake_followup["required_before_paid_delivery"], 3)
        self.assertEqual(
            [field["field"] for field in intake_followup["requested_fields"]],
            [
                "preferred_languages",
                "minimum_payout_usd",
                "allowed_risk_levels",
                "public_state_recheck_window",
            ],
        )
        self.assertIn("PatchRail copy-brief", intake_followup["next_internal_action"])
        self.assertIn("not customer-facing email copy", intake_followup["boundary"])
        cash_path_status = payload["cash_path_status"]
        self.assertEqual(cash_path_status["status"], "needs_buyer_intake")
        self.assertEqual(cash_path_status["next_revenue_action"], "collect_buyer_intake")
        self.assertTrue(cash_path_status["copy_brief_facts_available"])
        self.assertFalse(cash_path_status["payment_route_allowed_now"])
        self.assertTrue(cash_path_status["requires_written_acceptance_before_payment_route"])
        self.assertFalse(cash_path_status["buyer_ready"])
        self.assertIn("internal structured handoff only", cash_path_status["boundary"])
        self.assertIn("does not create a payment route", cash_path_status["boundary"])
        self.assertIn("does not authorize claims", cash_path_status["boundary"])
        operator_next_steps = payload["operator_next_steps"]
        self.assertEqual(
            operator_next_steps["schema_version"],
            "patchrail.funded_issues.operator_next_steps.v1",
        )
        self.assertEqual(operator_next_steps["status"], "needs_buyer_intake")
        self.assertEqual(operator_next_steps["primary_action"], "collect_buyer_intake")
        self.assertFalse(operator_next_steps["external_body_allowed"])
        self.assertFalse(operator_next_steps["payment_route_allowed_now"])
        self.assertEqual(
            [step["action"] for step in operator_next_steps["steps"]],
            [
                "collect_buyer_intake",
                "run_read_only_recheck",
                "preserve_no_go_evidence",
            ],
        )
        self.assertTrue(operator_next_steps["steps"][0]["copy_brief_allowed"])
        self.assertTrue(operator_next_steps["steps"][0]["blocks_paid_delivery"])
        self.assertIn(
            "preferred_languages",
            operator_next_steps["steps"][0]["evidence_required"],
        )
        self.assertIn("example/project#42", operator_next_steps["steps"][1]["reference_scope"])
        self.assertFalse(operator_next_steps["steps"][2]["blocks_paid_delivery"])
        self.assertIn("does not write external prose", operator_next_steps["boundary"])
        self.assertEqual(payload["top_safe_candidates"][0]["reference"], "example/project#42")
        self.assertEqual(payload["top_safe_candidates"][0]["opportunity_state"], "active")
        self.assertIn("ranking_by_money_only", payload["blocked_actions"])
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_funded_issues_report_markdown_preserves_read_only_boundary(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "report",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--safe-only",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Report", proc.stdout)
        self.assertIn("## Decision Summary", proc.stdout)
        self.assertIn("Candidate rows: `1`", proc.stdout)
        self.assertIn("Recommended batch action", proc.stdout)
        self.assertIn("`go_after_recheck` | 1", proc.stdout)
        self.assertIn("## Delivery Budget", proc.stdout)
        self.assertIn("Suggested package: `mini_diagnostic`", proc.stdout)
        self.assertIn("Estimated local review: `13` minutes", proc.stdout)
        self.assertIn("l2_scope_and_readiness_review", proc.stdout)
        self.assertIn("## Delivery Pack", proc.stdout)
        self.assertIn("l2_shortlist_readiness_review", proc.stdout)
        self.assertIn("Candidate references: `example/project#42`", proc.stdout)
        self.assertIn("No-go references: `example/toolkit#17`", proc.stdout)
        self.assertIn("## Source Quality", proc.stdout)
        self.assertIn("Status: `candidate_sources_available`", proc.stdout)
        self.assertIn("Candidate sources: `1`", proc.stdout)
        self.assertIn("No-go-only sources: `1`", proc.stdout)
        self.assertIn("Next tracker action: Run read-only public-state recheck", proc.stdout)
        self.assertIn("`polar` | 1 | 1 | 0 | 1", proc.stdout)
        self.assertIn("`algora` | 1 | 0 | 1 | 0", proc.stdout)
        self.assertIn("Source summary is local tracker evidence only", proc.stdout)
        self.assertIn("read-only benchmarking", proc.stdout)
        self.assertIn("## Recheck Plan", proc.stdout)
        self.assertIn("Active rechecks: `1`", proc.stdout)
        self.assertIn("`recheck_public_issue_state` | 1", proc.stdout)
        self.assertIn("read-only tracker triage", proc.stdout)
        self.assertIn("## Client Fit Summary", proc.stdout)
        self.assertIn("Status: `no_profile`", proc.stdout)
        self.assertIn("Matching rows: `2` / `2`", proc.stdout)
        self.assertIn("## Intake Follow-Up", proc.stdout)
        self.assertIn("Status: `needs_buyer_intake`", proc.stdout)
        self.assertIn("`preferred_languages`", proc.stdout)
        self.assertIn("not customer-facing email copy", proc.stdout)
        self.assertIn("## Operator Next Steps", proc.stdout)
        self.assertIn("Primary action: `collect_buyer_intake`", proc.stdout)
        self.assertIn("`preserve_no_go_evidence`", proc.stdout)
        self.assertIn("External body allowed: `False`", proc.stdout)
        self.assertIn("does not write external prose", proc.stdout)
        self.assertIn("## Cash Path Status", proc.stdout)
        self.assertIn("Next revenue action: `collect_buyer_intake`", proc.stdout)
        self.assertIn("Payment route allowed now: `False`", proc.stdout)
        self.assertIn("does not create a payment route", proc.stdout)
        self.assertIn("paid scope", proc.stdout)
        self.assertIn("## No-Go Moat", proc.stdout)
        self.assertIn("High-risk or excluded | 1", proc.stdout)
        self.assertIn("Stale or closed | 1", proc.stdout)
        self.assertIn("### Opportunity States", proc.stdout)
        self.assertIn("`active`: `1`", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertIn("example/toolkit#17", proc.stdout)
        self.assertIn("does not claim rewards", proc.stdout)
        self.assertIn("automatic_issue_comments", proc.stdout)

    def test_funded_issues_report_filters_by_active_state_for_tracker_metrics(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "report",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--opportunity-state",
                "active",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["opportunity_state"], "active")
        self.assertEqual(payload["totals"]["in_scope"], 1)
        self.assertEqual(payload["totals"]["safe_to_list"], 1)
        self.assertEqual(payload["breakdown"]["opportunity_states"], {"active": 1})
        self.assertEqual(payload["no_go_moat"]["stale_or_closed"], 0)

    def test_funded_issues_report_filters_by_risk_level_for_no_go_moat(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "report",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--risk-level",
                "high",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["risk_level"], "high")
        self.assertEqual(payload["totals"]["in_scope"], 1)
        self.assertEqual(payload["totals"]["safe_to_list"], 0)
        self.assertEqual(payload["breakdown"]["risk_levels"], {"high": 1})
        self.assertEqual(payload["breakdown"]["opportunity_states"], {"closed": 1})
        self.assertEqual(payload["no_go_moat"]["high_risk_or_excluded"], 1)
        self.assertEqual(payload["top_safe_candidates"], [])

    def test_funded_issues_recheck_queue_builds_local_read_only_work_queue(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "recheck-queue",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.recheck_queue.v1")
        self.assertEqual(payload["source_schema_version"], "patchrail.funded_issues.v1")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["safe_only"])
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_scored"], 2)
        self.assertIsNone(payload["queue_limit"])
        self.assertEqual(payload["queue_rows_before_limit"], 1)
        self.assertEqual(payload["queue_rows"], 1)
        self.assertEqual(payload["no_go_archive_rows"], 1)
        self.assertEqual(payload["priority_counts"], {"high": 1})
        self.assertEqual(
            payload["action_counts"],
            {"archive_as_no_go_evidence": 1, "recheck_public_issue_state": 1},
        )
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])
        self.assertFalse(payload["requirements"]["external_model_required"])
        self.assertFalse(payload["requirements"]["billing_required"])
        self.assertIn("automatic_pull_requests", payload["blocked_actions"])
        self.assertIn("mass_outreach", payload["blocked_actions"])
        row = payload["items"][0]
        self.assertEqual(row["reference"], "example/project#42")
        self.assertEqual(row["platform"], "polar")
        self.assertEqual(row["funding"], "250 USD")
        self.assertEqual(row["priority"], "high")
        self.assertEqual(row["action"], "recheck_public_issue_state")
        self.assertEqual(row["decision_gate"], "go_after_recheck")
        self.assertIn("confirm issue is still open", row["evidence_checklist"][0])
        self.assertIn("confirm funding is still visible", row["evidence_checklist"][2])
        self.assertIn("does not claim rewards", payload["boundary"])
        self.assertIn("guarantee merge or payout outcomes", payload["boundary"])

    def test_funded_issues_recheck_queue_can_limit_active_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            payload = json.loads(
                Path("examples/funded-issues-readonly/issues.json").read_text(encoding="utf-8")
            )
            second_active = json.loads(json.dumps(payload["issues"][0]))
            second_active["id"] = "polar-example-project-43"
            second_active["issue_number"] = 43
            second_active["url"] = "https://github.com/example/project/issues/43"
            second_active["title"] = "Document flaky integration test repro"
            payload["issues"].append(second_active)
            source.write_text(json.dumps(payload), encoding="utf-8")

            proc = run_patchrail(
                [
                    "funded-issues",
                    "recheck-queue",
                    "--source",
                    str(source),
                    "--max-rows",
                    "1",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["queue_limit"], 1)
        self.assertEqual(result["queue_rows_before_limit"], 2)
        self.assertEqual(result["queue_rows"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["reference"], "example/project#42")

    def test_funded_issues_recheck_queue_rejects_zero_limit(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "recheck-queue",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--max-rows",
                "0",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("max_rows must be at least 1", proc.stderr)

    def test_funded_issues_recheck_queue_markdown_preserves_boundaries(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "recheck-queue",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--safe-only",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Recheck Queue", proc.stdout)
        self.assertIn("- Read-only: `True`", proc.stdout)
        self.assertIn("- Safe-only: `True`", proc.stdout)
        self.assertIn("- Queue limit: `None`", proc.stdout)
        self.assertIn("- Queue rows before limit: `1`", proc.stdout)
        self.assertIn("- Queue rows: `1`", proc.stdout)
        self.assertIn("- No-go archive rows: `0`", proc.stdout)
        self.assertIn("| `high` | `recheck_public_issue_state` |", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertIn("confirm issue is still open", proc.stdout)
        self.assertIn("confirm funding is still visible", proc.stdout)
        self.assertIn("`recheck_public_issue_state` | 1", proc.stdout)
        self.assertIn("does not claim rewards", proc.stdout)
        self.assertIn("automatic_claims", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)

    def test_funded_issues_cash_actions_builds_internal_revenue_queue(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "cash-actions",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.cash_actions.v1")
        self.assertEqual(payload["source_schema_version"], "patchrail.funded_issues.v1")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["safe_only"])
        self.assertIsNone(payload["action_limit"])
        self.assertEqual(payload["actions_before_limit"], 2)
        self.assertEqual(payload["action_rows"], 2)
        self.assertEqual(
            payload["cash_path_status"]["next_revenue_action"],
            "collect_buyer_intake",
        )
        self.assertFalse(payload["cash_path_status"]["payment_route_allowed_now"])
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])
        self.assertFalse(payload["requirements"]["external_model_required"])
        self.assertFalse(payload["requirements"]["billing_required"])
        self.assertIn("automatic_pull_requests", payload["blocked_actions"])
        self.assertIn("mass_outreach", payload["blocked_actions"])
        first = payload["items"][0]
        self.assertEqual(first["action"], "collect_buyer_intake")
        self.assertEqual(first["priority"], "high")
        self.assertEqual(first["suggested_package"], "mini_diagnostic")
        self.assertTrue(first["copy_brief_allowed"])
        self.assertEqual(
            first["copy_brief_facts"]["schema_version"],
            "patchrail.funded_issues.copy_brief_facts.v1",
        )
        self.assertEqual(first["copy_brief_facts"]["type"], "reply")
        self.assertEqual(first["copy_brief_facts"]["goal"], "collect_buyer_intake")
        self.assertIn(
            "requested_fields=preferred_languages,minimum_payout_usd,allowed_risk_levels",
            first["copy_brief_facts"]["key_facts"],
        )
        self.assertIn(
            "evidence_references=example/project#42",
            first["copy_brief_facts"]["key_facts"],
        )
        self.assertEqual(
            first["copy_brief_facts"]["forbidden_fields"],
            ["body", "draft", "email_body"],
        )
        self.assertNotIn("body", first["copy_brief_facts"])
        self.assertNotIn("draft", first["copy_brief_facts"])
        self.assertNotIn("email_body", first["copy_brief_facts"])
        self.assertFalse(first["copy_brief_facts"]["external_body_allowed"])
        self.assertFalse(first["copy_brief_facts"]["payment_route_allowed_now"])
        self.assertFalse(first["external_body_allowed"])
        self.assertFalse(first["payment_route_allowed_now"])
        self.assertTrue(first["requires_written_acceptance_before_payment_route"])
        self.assertIn("preferred_languages", first["requested_fields"])
        self.assertIn("minimum_payout_usd", first["requested_fields"])
        self.assertIn("example/project#42", first["evidence_references"])
        self.assertIn("Do not write external prose", first["boundary"])
        second = payload["items"][1]
        self.assertEqual(second["action"], "run_read_only_recheck")
        self.assertEqual(second["priority"], "medium")
        self.assertFalse(second["copy_brief_allowed"])
        self.assertIsNone(second["copy_brief_facts"])
        self.assertIn("example/project#42", second["evidence_references"])
        self.assertEqual(
            payload["operator_next_steps"]["primary_action"],
            "collect_buyer_intake",
        )
        self.assertEqual(len(payload["operator_next_steps"]["steps"]), 3)
        self.assertFalse(payload["operator_next_steps"]["external_body_allowed"])
        self.assertFalse(payload["operator_next_steps"]["payment_route_allowed_now"])
        self.assertIn("not external prose", payload["boundary"])
        self.assertIn("do not create a payment route", payload["boundary"])
        self.assertIn("guarantee merge or payout outcomes", payload["boundary"])

    def test_funded_issues_cash_actions_markdown_preserves_boundaries(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "cash-actions",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--max-actions",
                "1",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Cash Actions", proc.stdout)
        self.assertIn("- Read-only: `True`", proc.stdout)
        self.assertIn("- Action limit: `1`", proc.stdout)
        self.assertIn("- Actions before limit: `2`", proc.stdout)
        self.assertIn("- Action rows: `1`", proc.stdout)
        self.assertIn("Next revenue action: `collect_buyer_intake`", proc.stdout)
        self.assertIn("Payment route allowed now: `False`", proc.stdout)
        self.assertIn("`collect_buyer_intake`", proc.stdout)
        self.assertIn("`mini_diagnostic`", proc.stdout)
        self.assertIn("`preferred_languages`", proc.stdout)
        self.assertIn("7 facts; forbidden:", proc.stdout)
        self.assertIn("`body`, `draft`, `email_body`", proc.stdout)
        self.assertIn("## Operator Next Steps", proc.stdout)
        self.assertIn("Primary action: `collect_buyer_intake`", proc.stdout)
        self.assertIn("not external prose", proc.stdout)
        self.assertIn("does not create a payment route", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)

    def test_funded_issues_cash_actions_rejects_zero_limit(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "cash-actions",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--max-actions",
                "0",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("max_actions must be at least 1", proc.stderr)

    def test_funded_issues_fulfillment_packet_builds_internal_delivery_packet(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "fulfillment-packet",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload["schema_version"],
            "patchrail.funded_issues.fulfillment_packet.v1",
        )
        self.assertEqual(payload["source_schema_version"], "patchrail.funded_issues.v1")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["safe_only"])
        self.assertEqual(payload["status"], "needs_buyer_intake")
        self.assertEqual(payload["suggested_package"], "mini_diagnostic")
        self.assertIsNone(payload["packet_limit"])
        self.assertEqual(payload["items_before_limit"], 3)
        self.assertEqual(payload["item_rows"], 3)
        self.assertEqual(payload["totals"]["loaded"], 2)
        self.assertEqual(payload["totals"]["candidate_references"], 1)
        self.assertEqual(payload["totals"]["no_go_references"], 1)
        self.assertEqual(payload["totals"]["active_rechecks"], 1)
        self.assertEqual(payload["totals"]["source_count"], 2)
        self.assertEqual(
            payload["cash_path_status"]["next_revenue_action"],
            "collect_buyer_intake",
        )
        self.assertFalse(payload["cash_path_status"]["payment_route_allowed_now"])
        gate_map = {gate["gate"]: gate for gate in payload["qa_gates"]}
        self.assertFalse(gate_map["buyer_intake_fields_complete"]["passed"])
        self.assertIn("preferred_languages", gate_map["buyer_intake_fields_complete"]["evidence"])
        self.assertFalse(gate_map["public_state_recheck_complete"]["passed"])
        self.assertIn("example/project#42", gate_map["public_state_recheck_complete"]["evidence"])
        self.assertTrue(gate_map["source_quality_recorded"]["passed"])
        self.assertTrue(gate_map["third_party_write_boundary"]["passed"])
        self.assertFalse(gate_map["payment_route_written_acceptance"]["passed"])
        readiness = payload["delivery_readiness"]
        self.assertFalse(readiness["ready_for_paid_delivery"])
        self.assertEqual(readiness["status"], "blocked_internal")
        self.assertEqual(readiness["next_internal_action"], "collect_buyer_intake")
        self.assertFalse(readiness["payment_route_allowed_now"])
        self.assertFalse(readiness["external_body_allowed"])
        self.assertIn("buyer_intake_fields_complete", readiness["blocking_gates"])
        self.assertIn("public_state_recheck_complete", readiness["blocking_gates"])
        self.assertIn("payment_route_written_acceptance", readiness["blocking_gates"])
        self.assertIn("collect_buyer_intake", readiness["blocking_item_actions"])
        self.assertIn("recheck_public_issue_state", readiness["blocking_item_actions"])
        self.assertIn("example/project#42", readiness["blocking_reference_scope"])
        self.assertIn("does not authorize", readiness["boundary"])
        self.assertEqual(
            payload["operator_next_steps"]["primary_action"],
            "collect_buyer_intake",
        )
        self.assertEqual(
            [step["source"] for step in payload["operator_next_steps"]["steps"]],
            ["cash_path", "recheck_plan", "delivery_pack"],
        )
        self.assertFalse(payload["operator_next_steps"]["external_body_allowed"])
        self.assertFalse(payload["operator_next_steps"]["payment_route_allowed_now"])
        self.assertFalse(payload["handoff"]["external_body_allowed"])
        self.assertFalse(payload["handoff"]["payment_route_allowed_now"])
        self.assertTrue(payload["handoff"]["requires_written_acceptance_before_payment_route"])
        self.assertIn("cash_actions", payload["handoff"]["sections"])
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])
        self.assertFalse(payload["requirements"]["external_model_required"])
        self.assertFalse(payload["requirements"]["billing_required"])
        self.assertIn("automatic_pull_requests", payload["blocked_actions"])
        self.assertIn("mass_outreach", payload["blocked_actions"])
        actions = [item["action"] for item in payload["items"]]
        self.assertEqual(
            actions,
            ["collect_buyer_intake", "recheck_public_issue_state", "run_read_only_recheck"],
        )
        first = payload["items"][0]
        self.assertEqual(first["stage"], "cash_path")
        self.assertIn("preferred_languages", first["evidence_required"])
        self.assertTrue(first["blocks_paid_delivery"])
        self.assertFalse(first["external_body_allowed"])
        self.assertFalse(first["payment_route_allowed_now"])
        self.assertFalse(first["github_write_permission_required"])
        self.assertFalse(first["network_required"])
        self.assertIn("Do not write customer prose", first["boundary"])
        self.assertIn("not customer-facing prose", payload["boundary"])
        self.assertIn("does not create a payment route", payload["boundary"])
        self.assertIn("guarantee merge or payout outcomes", payload["boundary"])

    def test_funded_issues_fulfillment_packet_markdown_preserves_boundaries(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "fulfillment-packet",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--max-items",
                "2",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Fulfillment Packet", proc.stdout)
        self.assertIn("- Read-only: `True`", proc.stdout)
        self.assertIn("- Status: `needs_buyer_intake`", proc.stdout)
        self.assertIn("- Packet limit: `2`", proc.stdout)
        self.assertIn("- Items before limit: `3`", proc.stdout)
        self.assertIn("- Item rows: `2`", proc.stdout)
        self.assertIn("## QA Gates", proc.stdout)
        self.assertIn("`buyer_intake_fields_complete`", proc.stdout)
        self.assertIn("`public_state_recheck_complete`", proc.stdout)
        self.assertIn("`payment_route_written_acceptance`", proc.stdout)
        self.assertIn("## Delivery Readiness", proc.stdout)
        self.assertIn("- Status: `blocked_internal`", proc.stdout)
        self.assertIn("- Ready for paid delivery: `False`", proc.stdout)
        self.assertIn("- Payment route allowed now: `False`", proc.stdout)
        self.assertIn("- External body allowed: `False`", proc.stdout)
        self.assertIn("`collect_buyer_intake`", proc.stdout)
        self.assertIn("## Operator Next Steps", proc.stdout)
        self.assertIn("`preserve_no_go_evidence`", proc.stdout)
        self.assertIn("## Fulfillment Items", proc.stdout)
        self.assertIn("`collect_buyer_intake`", proc.stdout)
        self.assertIn("`recheck_public_issue_state`", proc.stdout)
        self.assertIn("`preferred_languages`", proc.stdout)
        self.assertIn("## Handoff", proc.stdout)
        self.assertIn("- External body allowed: `False`", proc.stdout)
        self.assertIn("- Payment route allowed now: `False`", proc.stdout)
        self.assertIn("not customer-facing prose", proc.stdout)
        self.assertIn("does not create a payment route", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)

    def test_funded_issues_fulfillment_packet_rejects_zero_limit(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "fulfillment-packet",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--max-items",
                "0",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("max_items must be at least 1", proc.stderr)

    def test_funded_issues_report_accepts_read_only_client_profile(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "report",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--profile",
                "examples/funded-issues-readonly/client-profile-python.json",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Client profile: `Async Python buyer`", proc.stdout)
        self.assertIn("In scope: `1`", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertIn("## Client Fit Summary", proc.stdout)
        self.assertIn("Status: `partial_match`", proc.stdout)
        self.assertIn("Matching rows: `1` / `2`", proc.stdout)
        self.assertIn("EXCLUDED_RISK_FLAG:spam_attractive", proc.stdout)
        self.assertIn("## Client Fit Gaps", proc.stdout)
        self.assertIn("example/toolkit#17", proc.stdout)
        self.assertIn("LANGUAGE_MISMATCH", proc.stdout)
        self.assertIn("OPPORTUNITY_STATE_NOT_ALLOWED", proc.stdout)
        self.assertIn("RISK_LEVEL_NOT_ALLOWED", proc.stdout)
        self.assertIn("EXCLUDED_RISK_FLAG:spam_attractive", proc.stdout)
        self.assertIn("## Intake Follow-Up", proc.stdout)
        self.assertIn("Status: `needs_buyer_intake`", proc.stdout)
        self.assertIn("`profile_gap_confirmation`", proc.stdout)
        self.assertIn("`public_state_recheck_window`", proc.stdout)
        self.assertIn("does not claim rewards", proc.stdout)

    def test_funded_issues_list_profile_preserves_filters_in_json(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "list",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--profile",
                "examples/funded-issues-readonly/client-profile-python.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_returned"], 1)
        self.assertEqual(payload["filters"]["profile"]["name"], "Async Python buyer")
        self.assertEqual(
            payload["filters"]["profile"]["schema_version"],
            "patchrail.funded_issues.client_profile.v1",
        )
        self.assertEqual(payload["filters"]["profile"]["languages"], ["python"])
        self.assertEqual(payload["filters"]["profile"]["min_usd"], 200.0)
        self.assertTrue(payload["filters"]["profile"]["read_only"])
        self.assertEqual(payload["issues"][0]["reference"], "example/project#42")

    def test_schema_command_exposes_funded_issues_report_and_shortlist_contracts(self) -> None:
        expected_versions = {
            "funded-issues-report": "patchrail.funded_issues.report.v1",
            "funded-issues-shortlist": "patchrail.funded_issues.shortlist.v1",
        }

        for schema_name, schema_version in expected_versions.items():
            with self.subTest(schema_name=schema_name):
                proc = run_patchrail(["schema", schema_name])

                self.assertEqual(proc.returncode, 0, proc.stderr)
                schema = json.loads(proc.stdout)
                self.assertIn("https://patchrail.dev/schemas/", schema["$id"])
                self.assertEqual(schema["properties"]["schema_version"]["const"], schema_version)
                self.assertEqual(schema["properties"]["read_only"]["const"], True)
                self.assertIn("blocked_actions", schema["required"])
                self.assertIn("requirements", schema["required"])
                self.assertIn("source_quality", schema["required"])
                self.assertIn("sources", schema["$defs"]["source_quality"]["required"])
                self.assertIn("summary", schema["$defs"]["source_quality"]["required"])
                source_summary = schema["$defs"]["source_quality_summary"]
                self.assertIn("candidate_source_count", source_summary["required"])
                self.assertIn("next_tracker_action", source_summary["required"])
                self.assertIn(
                    "candidate_sources_available",
                    source_summary["properties"]["status"]["enum"],
                )
                self.assertIn("recheck_plan", schema["required"])
                self.assertIn("next_rows", schema["$defs"]["recheck_plan"]["required"])
                self.assertIn("action", schema["$defs"]["recheck_row"]["required"])
                self.assertIn(
                    "recheck_public_issue_state",
                    schema["$defs"]["recheck_row"]["properties"]["action"]["enum"],
                )
                self.assertIn("client_fit_gaps", schema["required"])
                self.assertIn("client_fit_summary", schema["required"])
                self.assertIn("intake_followup", schema["required"])
                self.assertIn("cash_path_status", schema["required"])
                intake_followup = schema["$defs"]["intake_followup"]
                self.assertIn("requested_fields", intake_followup["required"])
                self.assertIn(
                    "needs_buyer_intake",
                    intake_followup["properties"]["status"]["enum"],
                )
                self.assertIn(
                    "ready_after_read_only_recheck",
                    intake_followup["properties"]["status"]["enum"],
                )
                intake_field = schema["$defs"]["intake_field"]
                self.assertIn("required_before_paid_delivery", intake_field["required"])
                cash_path_status = schema["$defs"]["cash_path_status"]
                self.assertIn("next_revenue_action", cash_path_status["required"])
                self.assertIn(
                    "collect_buyer_intake",
                    cash_path_status["properties"]["next_revenue_action"]["enum"],
                )
                self.assertEqual(
                    cash_path_status["properties"]["payment_route_allowed_now"]["const"],
                    False,
                )
                self.assertEqual(
                    cash_path_status["properties"][
                        "requires_written_acceptance_before_payment_route"
                    ]["const"],
                    True,
                )
                client_fit_summary = schema["$defs"]["client_fit_summary"]
                self.assertIn("matching_rows", client_fit_summary["required"])
                self.assertIn("partial_match", client_fit_summary["properties"]["status"]["enum"])
                self.assertIn("gap_counts", client_fit_summary["required"])
                client_fit_gap = schema["$defs"]["client_fit_gap"]
                self.assertIn("gap_codes", client_fit_gap["required"])
                self.assertIn("gap_summary", client_fit_gap["required"])
                source_stats = schema["$defs"]["source_quality_source"]
                self.assertIn("usable_signal_ratio", source_stats["required"])
                self.assertIn("recommended_use", source_stats["required"])
                requirements = schema["$defs"]["safe_requirements"]["properties"]
                self.assertEqual(requirements["network_required"]["const"], False)
                self.assertEqual(requirements["github_write_permission_required"]["const"], False)
                self.assertEqual(requirements["external_model_required"]["const"], False)
                self.assertEqual(requirements["billing_required"]["const"], False)
                filters = schema["$defs"]["filters"]
                self.assertIn("opportunity_state", filters["required"])
                self.assertIn("opportunity_state", filters["properties"])
                self.assertIn("risk_level", filters["required"])
                self.assertIn("risk_level", filters["properties"])
                self.assertIn("profile", filters["required"])
                self.assertIn("profile", filters["properties"])
                profile_schema = schema["$defs"]["client_profile"]
                self.assertEqual(
                    profile_schema["properties"]["schema_version"]["const"],
                    "patchrail.funded_issues.client_profile.v1",
                )
                self.assertIn("allowed_opportunity_states", profile_schema["required"])
                self.assertIn("allowed_risk_levels", profile_schema["required"])
                self.assertIn("excluded_risk_flags", profile_schema["required"])
                self.assertEqual(profile_schema["properties"]["read_only"]["const"], True)

                blocked_actions = schema["$defs"]["blocked_actions"]["items"]["enum"]
                self.assertIn("automatic_claims", blocked_actions)
                self.assertIn("automatic_pull_requests", blocked_actions)
                self.assertIn("automatic_issue_comments", blocked_actions)
                self.assertIn("mass_outreach", blocked_actions)
                self.assertIn("ranking_by_money_only", blocked_actions)
                self.assertIn("decision_summary", schema["required"])
                self.assertIn("delivery_budget", schema["required"])
                self.assertIn("delivery_pack", schema["required"])
                self.assertIn("handoff", schema["$defs"]["delivery_pack"]["required"])
                self.assertIn("phases", schema["$defs"]["delivery_pack"]["required"])
                self.assertIn(
                    "l2_shortlist_readiness_review",
                    schema["$defs"]["delivery_phase"]["properties"]["phase"]["enum"],
                )

                if schema_name == "funded-issues-shortlist":
                    self.assertIn(
                        "recommended_batch_action",
                        schema["$defs"]["decision_summary"]["required"],
                    )
                    self.assertIn(
                        "suggested_package",
                        schema["$defs"]["delivery_budget"]["required"],
                    )
                    self.assertIn(
                        "opportunity_shortlist",
                        schema["$defs"]["delivery_budget"]["properties"]["suggested_package"][
                            "enum"
                        ],
                    )
                    self.assertIn("shortlist", schema["required"])
                    self.assertIn("no_go_evidence", schema["required"])
                    self.assertEqual(
                        schema["$defs"]["scored_issue"]["properties"]["score"]["maximum"], 100
                    )
                    self.assertIn(
                        "confidence",
                        schema["$defs"]["scored_issue"]["required"],
                    )
                    self.assertEqual(
                        schema["$defs"]["scored_issue"]["properties"]["confidence"]["maximum"], 1
                    )
                    self.assertIn(
                        "recommended_next_step",
                        schema["$defs"]["scored_issue"]["required"],
                    )
                    self.assertIn(
                        "decision_gate",
                        schema["$defs"]["scored_issue"]["required"],
                    )
                    self.assertIn(
                        "source_review",
                        schema["$defs"]["funded_issue"]["required"],
                    )
                    self.assertIn(
                        "primary_source_required",
                        schema["$defs"]["source_review"]["required"],
                    )
                    self.assertIn(
                        "discovery_only_source",
                        schema["$defs"]["source_review"]["properties"]["risk_flags"]["items"][
                            "enum"
                        ],
                    )
                    self.assertIn(
                        "needs_funding_verification",
                        schema["$defs"]["scored_issue"]["properties"]["decision_gate"]["enum"],
                    )
                else:
                    self.assertIn(
                        "safety_boundary",
                        schema["$defs"]["decision_summary"]["required"],
                    )
                    self.assertIn(
                        "within_margin_budget",
                        schema["$defs"]["delivery_budget"]["required"],
                    )
                    self.assertIn("top_safe_candidates", schema["required"])
                    self.assertIn("no_go_moat", schema["required"])

    def test_funded_issues_score_ranks_readiness_with_reason_codes(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "score",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.score.v1")
        self.assertEqual(payload["read_only"], True)
        self.assertEqual(payload["total_loaded"], 2)
        self.assertEqual(payload["total_scored"], 2)
        self.assertEqual(payload["rating_counts"], {"go_candidate": 1, "no_go": 1})
        self.assertEqual(payload["scores"][0]["issue"]["reference"], "example/project#42")
        self.assertEqual(payload["scores"][0]["score"], 99)
        self.assertEqual(payload["scores"][0]["confidence"], 0.99)
        self.assertEqual(payload["scores"][0]["rating"], "go_candidate")
        self.assertEqual(payload["scores"][0]["decision_gate"], "go_after_recheck")
        self.assertEqual(payload["scores"][0]["reason_codes"], ["NO_MAJOR_REVIEW_GAPS"])
        self.assertIn("Reproduce locally", payload["scores"][0]["recommended_next_step"])
        self.assertIn("re-check assignment", payload["scores"][0]["recommended_next_step"])
        risky = payload["scores"][1]
        self.assertEqual(risky["issue"]["reference"], "example/toolkit#17")
        self.assertEqual(risky["issue"]["opportunity_state"], "closed")
        self.assertEqual(risky["score"], 0)
        self.assertEqual(risky["confidence"], 0.3)
        self.assertEqual(risky["rating"], "no_go")
        self.assertEqual(risky["decision_gate"], "no_go")
        self.assertIn("CLOSED_OR_INACTIVE", risky["reason_codes"])
        self.assertIn("SCOPE_TOO_BROAD", risky["reason_codes"])
        self.assertIn("SPAM_ATTRACTIVE", risky["reason_codes"])
        self.assertIn("NO_CONTRIBUTION_GUIDELINES", risky["reason_codes"])
        self.assertIn("Do not engage", risky["recommended_next_step"])
        self.assertIn("live again", risky["recommended_next_step"])
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])
        self.assertIn("ranking_by_money_only", payload["blocked_actions"])

    def test_funded_issues_score_safe_only_filters_high_risk(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "score",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--safe-only",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Score", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertNotIn("example/toolkit#17", proc.stdout)
        self.assertIn("Recommended next step", proc.stdout)
        self.assertIn("claim rewards", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)

    def test_funded_issues_score_filters_by_closed_state(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "score",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--opportunity-state",
                "closed",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["opportunity_state"], "closed")
        self.assertEqual(payload["total_scored"], 1)
        self.assertEqual(payload["rating_counts"], {"no_go": 1})
        self.assertEqual(payload["scores"][0]["issue"]["reference"], "example/toolkit#17")
        self.assertIn("CLOSED_OR_INACTIVE", payload["scores"][0]["reason_codes"])

    def test_funded_issues_score_filters_by_low_risk_candidates(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "score",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--risk-level",
                "low",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["risk_level"], "low")
        self.assertEqual(payload["total_scored"], 1)
        self.assertEqual(payload["rating_counts"], {"go_candidate": 1})
        self.assertEqual(payload["scores"][0]["issue"]["reference"], "example/project#42")
        self.assertEqual(payload["scores"][0]["issue"]["risk_level"], "low")

    def test_funded_issues_score_marks_unclear_funding_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "unclear",
                                "platform": "github",
                                "repository": "example/unclear",
                                "issue_number": 8,
                                "title": "Investigate funded but unverified issue",
                                "url": "https://github.com/example/unclear/issues/8",
                                "language": "python",
                                "labels": ["bug"],
                                "opportunity_state": "unknown",
                                "contribution_signals": ["reproduction included"],
                                "risk_flags": [],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/unclear/blob/main/CONTRIBUTING.md"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "score",
                    "--source",
                    str(source),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["scores"][0]["decision_gate"], "needs_funding_verification")
        self.assertIn("FUNDING_STATE_UNCLEAR", payload["scores"][0]["reason_codes"])
        self.assertIn("OPPORTUNITY_STATE_UNCLEAR", payload["scores"][0]["reason_codes"])

    def test_funded_issues_score_requires_primary_source_for_discovery_only_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "discovery-only",
                                "platform": "github_l0_l1_review",
                                "repository": "example/discovery",
                                "issue_number": 51,
                                "title": "Funded signal seen through aggregator only",
                                "url": "https://github.com/example/discovery/issues/51",
                                "funding": {"amount": 400, "currency": "USD"},
                                "language": "python",
                                "labels": ["bug"],
                                "opportunity_state": "active",
                                "contribution_signals": [
                                    "reproduction included",
                                    "tests referenced",
                                    "clear failure mode",
                                ],
                                "risk_flags": ["discovery_only_source"],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/discovery/blob/main/CONTRIBUTING.md"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            score_proc = run_patchrail(
                [
                    "funded-issues",
                    "score",
                    "--source",
                    str(source),
                    "--format",
                    "json",
                ]
            )
            report_proc = run_patchrail(
                [
                    "funded-issues",
                    "report",
                    "--source",
                    str(source),
                    "--format",
                    "json",
                ]
            )
            shortlist_proc = run_patchrail(
                [
                    "funded-issues",
                    "shortlist",
                    "--source",
                    str(source),
                    "--safe-only",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(score_proc.returncode, 0, score_proc.stderr)
        score_payload = json.loads(score_proc.stdout)
        row = score_payload["scores"][0]
        self.assertEqual(row["issue"]["reference"], "example/discovery#51")
        self.assertEqual(row["rating"], "watchlist")
        self.assertEqual(row["decision_gate"], "needs_funding_verification")
        self.assertFalse(row["issue"]["safe_to_list"])
        self.assertTrue(row["issue"]["source_review"]["primary_source_required"])
        self.assertTrue(row["issue"]["source_review"]["required_before_shortlist"])
        self.assertEqual(row["issue"]["source_review"]["risk_flags"], ["discovery_only_source"])
        self.assertIn("DISCOVERY_ONLY_SOURCE", row["reason_codes"])
        self.assertIn("permitted primary public/API source", row["recommended_next_step"])

        self.assertEqual(report_proc.returncode, 0, report_proc.stderr)
        report_payload = json.loads(report_proc.stdout)
        self.assertEqual(report_payload["totals"]["safe_to_list"], 0)
        self.assertEqual(report_payload["decision_summary"]["verification_needed"], 1)
        self.assertEqual(
            report_payload["source_quality"]["summary"]["funding_verification_needed"],
            1,
        )
        self.assertEqual(
            report_payload["source_quality"]["summary"]["status"],
            "needs_funding_verification",
        )
        self.assertEqual(
            report_payload["recheck_plan"]["action_counts"],
            {"verify_funding_visibility": 1},
        )
        self.assertEqual(
            report_payload["recheck_plan"]["next_rows"][0]["action"],
            "verify_funding_visibility",
        )

        self.assertEqual(shortlist_proc.returncode, 0, shortlist_proc.stderr)
        shortlist_payload = json.loads(shortlist_proc.stdout)
        self.assertEqual(shortlist_payload["shortlist"], [])
        self.assertEqual(shortlist_payload["decision_summary"]["verification_needed"], 1)

    def test_funded_issues_score_marks_authorization_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "authorization",
                                "platform": "algora",
                                "repository": "example/authorization",
                                "issue_number": 12,
                                "title": "Requires private maintainer contact",
                                "url": "https://github.com/example/authorization/issues/12",
                                "funding": {"amount": 1000, "currency": "USD"},
                                "language": "typescript",
                                "labels": ["integration"],
                                "opportunity_state": "active",
                                "contribution_signals": ["requires maintainer confirmation"],
                                "risk_flags": ["requires_external_contact"],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/authorization/blob/main/CONTRIBUTING.md"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "score",
                    "--source",
                    str(source),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["scores"][0]["decision_gate"], "needs_authorization")
        self.assertIn("NEEDS_AUTHORIZATION", payload["scores"][0]["reason_codes"])

    def test_funded_issues_shortlist_builds_decision_support_artifact(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.funded_issues.shortlist.v1")
        self.assertEqual(payload["read_only"], True)
        self.assertEqual(payload["summary"]["total_loaded"], 2)
        self.assertEqual(payload["client_fit_gaps"], [])
        self.assertEqual(payload["summary"]["opportunity_states"], {"active": 1, "closed": 1})
        self.assertEqual(payload["summary"]["rating_counts"], {"go_candidate": 1, "no_go": 1})
        self.assertEqual(payload["shortlist"][0]["issue"]["reference"], "example/project#42")
        self.assertEqual(payload["shortlist"][0]["confidence"], 0.99)
        self.assertEqual(payload["shortlist"][0]["rating"], "go_candidate")
        self.assertEqual(payload["shortlist"][0]["decision_gate"], "go_after_recheck")
        self.assertIn("Reproduce locally", payload["shortlist"][0]["recommended_next_step"])
        self.assertEqual(payload["no_go_evidence"][0]["issue"]["reference"], "example/toolkit#17")
        self.assertEqual(payload["no_go_evidence"][0]["issue"]["opportunity_state"], "closed")
        self.assertEqual(payload["no_go_evidence"][0]["confidence"], 0.3)
        self.assertEqual(payload["no_go_evidence"][0]["rating"], "no_go")
        self.assertEqual(payload["no_go_evidence"][0]["decision_gate"], "no_go")
        self.assertIn("Do not engage", payload["no_go_evidence"][0]["recommended_next_step"])
        self.assertEqual(payload["no_go_moat"]["ambiguous_scope"], 1)
        self.assertEqual(payload["no_go_moat"]["stale_or_closed"], 1)
        self.assertEqual(payload["decision_summary"]["candidate_rows"], 1)
        self.assertEqual(payload["decision_summary"]["no_go_rows"], 1)
        self.assertEqual(payload["decision_summary"]["gate_counts"]["go_after_recheck"], 1)
        self.assertEqual(payload["decision_summary"]["gate_counts"]["no_go"], 1)
        self.assertIn(
            "verify public state",
            payload["decision_summary"]["recommended_batch_action"],
        )
        self.assertIn("do not claim", payload["decision_summary"]["safety_boundary"])
        self.assertEqual(payload["delivery_budget"]["suggested_package"], "mini_diagnostic")
        self.assertEqual(payload["delivery_budget"]["estimated_review_minutes"], 13)
        self.assertTrue(payload["delivery_budget"]["within_margin_budget"])
        self.assertEqual(
            payload["delivery_budget"]["analysis_rows"]["l1_state_and_noise_review"], 1
        )
        self.assertEqual(
            payload["delivery_budget"]["analysis_rows"]["l2_scope_and_readiness_review"], 1
        )
        self.assertEqual(payload["delivery_pack"]["suggested_package"], "mini_diagnostic")
        self.assertEqual(
            payload["delivery_pack"]["handoff"]["candidate_references"],
            ["example/project#42"],
        )
        self.assertEqual(
            payload["delivery_pack"]["handoff"]["no_go_references"],
            ["example/toolkit#17"],
        )
        self.assertEqual(
            payload["delivery_pack"]["phases"][1]["phase"],
            "l2_shortlist_readiness_review",
        )
        self.assertEqual(
            payload["delivery_pack"]["phases"][1]["references"],
            ["example/project#42"],
        )
        source_quality = payload["source_quality"]
        self.assertEqual(source_quality["sources"]["polar"]["candidate_rows"], 1)
        self.assertEqual(source_quality["sources"]["polar"]["usable_signal_ratio"], 1)
        self.assertEqual(source_quality["sources"]["algora"]["no_go_rows"], 1)
        self.assertEqual(source_quality["sources"]["algora"]["usable_signal_ratio"], 0)
        self.assertIn("read-only benchmarking", source_quality["boundary"])
        self.assertEqual(payload["recheck_plan"]["recheck_rows"], 1)
        self.assertEqual(payload["recheck_plan"]["no_go_rows"], 1)
        self.assertEqual(
            payload["recheck_plan"]["next_rows"][0]["action"],
            "recheck_public_issue_state",
        )
        client_fit_summary = payload["client_fit_summary"]
        self.assertEqual(client_fit_summary["status"], "no_profile")
        self.assertEqual(client_fit_summary["matching_rows"], 2)
        self.assertEqual(client_fit_summary["excluded_rows"], 0)
        intake_followup = payload["intake_followup"]
        self.assertEqual(intake_followup["status"], "needs_buyer_intake")
        self.assertEqual(intake_followup["required_before_paid_delivery"], 3)
        self.assertEqual(
            intake_followup["requested_fields"][0]["field"],
            "preferred_languages",
        )
        cash_path_status = payload["cash_path_status"]
        self.assertEqual(cash_path_status["status"], "needs_buyer_intake")
        self.assertEqual(cash_path_status["next_revenue_action"], "collect_buyer_intake")
        self.assertTrue(cash_path_status["copy_brief_facts_available"])
        self.assertFalse(cash_path_status["payment_route_allowed_now"])
        self.assertTrue(cash_path_status["requires_written_acceptance_before_payment_route"])
        self.assertFalse(cash_path_status["buyer_ready"])
        self.assertIn("internal structured handoff only", cash_path_status["boundary"])
        self.assertIn("does not authorize claims", cash_path_status["boundary"])
        self.assertIn("automatic_claims", payload["blocked_actions"])
        self.assertIn("automatic_issue_comments", payload["blocked_actions"])
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])
        self.assertFalse(payload["requirements"]["billing_required"])
        self.assertIn("Decision support only", payload["boundary"])
        self.assertIn("guarantee merge or payout", payload["boundary"])

    def test_funded_issues_shortlist_markdown_preserves_no_go_boundary(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--format",
                "markdown",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Shortlist", proc.stdout)
        self.assertIn("## Decision Summary", proc.stdout)
        self.assertIn("Candidate rows: `1`", proc.stdout)
        self.assertIn("No-go rows: `1`", proc.stdout)
        self.assertIn("`no_go` | 1", proc.stdout)
        self.assertIn("## Delivery Budget", proc.stdout)
        self.assertIn("Suggested package: `mini_diagnostic`", proc.stdout)
        self.assertIn("Estimated local review: `13` minutes", proc.stdout)
        self.assertIn("## Delivery Pack", proc.stdout)
        self.assertIn("Candidate references: `example/project#42`", proc.stdout)
        self.assertIn("No-go references: `example/toolkit#17`", proc.stdout)
        self.assertIn("## Source Quality", proc.stdout)
        self.assertIn("`polar` | 1 | 1 | 0 | 1", proc.stdout)
        self.assertIn("`algora` | 1 | 0 | 1 | 0", proc.stdout)
        self.assertIn("## Recheck Plan", proc.stdout)
        self.assertIn("Archived no-go rows: `1`", proc.stdout)
        self.assertIn("`archive_as_no_go_evidence` | 1", proc.stdout)
        self.assertIn("## Client Fit Summary", proc.stdout)
        self.assertIn("Status: `no_profile`", proc.stdout)
        self.assertIn("## Intake Follow-Up", proc.stdout)
        self.assertIn("Status: `needs_buyer_intake`", proc.stdout)
        self.assertIn("`minimum_payout_usd`", proc.stdout)
        self.assertIn("## Cash Path Status", proc.stdout)
        self.assertIn("Next revenue action: `collect_buyer_intake`", proc.stdout)
        self.assertIn("Payment route allowed now: `False`", proc.stdout)
        self.assertIn("does not create a payment route", proc.stdout)
        self.assertIn("## Shortlist", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertIn("Confidence: `0.99`", proc.stdout)
        self.assertIn("Decision gate", proc.stdout)
        self.assertIn("go_after_recheck", proc.stdout)
        self.assertIn("## No-Go Evidence", proc.stdout)
        self.assertIn("example/toolkit#17", proc.stdout)
        self.assertIn("Recommended next step", proc.stdout)
        self.assertIn("Decision support only", proc.stdout)
        self.assertIn("automatic_pull_requests", proc.stdout)

    def test_funded_issues_shortlist_limit_caps_candidate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.v1",
                        "issues": [
                            {
                                "id": "one",
                                "platform": "polar",
                                "repository": "example/one",
                                "issue_number": 1,
                                "title": "Fix deterministic CI failure",
                                "url": "https://github.com/example/one/issues/1",
                                "funding": {"amount": 100, "currency": "USD"},
                                "language": "python",
                                "opportunity_state": "active",
                                "labels": ["bug"],
                                "contribution_signals": ["reproduction included"],
                                "risk_flags": [],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/one/blob/main/CONTRIBUTING.md"
                                ),
                            },
                            {
                                "id": "two",
                                "platform": "polar",
                                "repository": "example/two",
                                "issue_number": 2,
                                "title": "Repair release workflow",
                                "url": "https://github.com/example/two/issues/2",
                                "funding": {"amount": 200, "currency": "USD"},
                                "language": "python",
                                "opportunity_state": "active",
                                "labels": ["ci"],
                                "contribution_signals": [
                                    "reproduction included",
                                    "failing CI linked",
                                ],
                                "risk_flags": [],
                                "contribution_guidelines_url": (
                                    "https://github.com/example/two/blob/main/CONTRIBUTING.md"
                                ),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "shortlist",
                    "--source",
                    str(source),
                    "--limit",
                    "1",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["limit"], 1)
        self.assertEqual(len(payload["shortlist"]), 1)
        self.assertEqual(payload["shortlist"][0]["issue"]["reference"], "example/two#2")
        self.assertEqual(payload["summary"]["rating_counts"], {"go_candidate": 2})

    def test_funded_issues_shortlist_filters_no_go_evidence_by_state(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--opportunity-state",
                "closed",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["opportunity_state"], "closed")
        self.assertEqual(payload["summary"]["in_scope"], 1)
        self.assertEqual(payload["shortlist"], [])
        self.assertEqual(len(payload["no_go_evidence"]), 1)
        self.assertEqual(payload["no_go_evidence"][0]["issue"]["reference"], "example/toolkit#17")

    def test_funded_issues_shortlist_filters_by_high_risk_no_go_evidence(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--risk-level",
                "high",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["risk_level"], "high")
        self.assertEqual(payload["summary"]["in_scope"], 1)
        self.assertEqual(payload["shortlist"], [])
        self.assertEqual(len(payload["no_go_evidence"]), 1)
        self.assertEqual(payload["no_go_evidence"][0]["issue"]["reference"], "example/toolkit#17")
        self.assertEqual(payload["no_go_moat"]["high_risk_or_excluded"], 1)

    def test_funded_issues_shortlist_filters_with_client_profile(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--profile",
                "examples/funded-issues-readonly/client-profile-python.json",
                "--format",
                "json",
            ]
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["profile"]["name"], "Async Python buyer")
        self.assertTrue(payload["filters"]["profile"]["read_only"])
        self.assertEqual(payload["summary"]["in_scope"], 1)
        self.assertEqual(payload["summary"]["safe_to_list"], 1)
        self.assertEqual(payload["summary"]["high_risk"], 0)
        self.assertEqual(payload["shortlist"][0]["issue"]["reference"], "example/project#42")
        self.assertEqual(payload["no_go_evidence"], [])
        self.assertEqual(len(payload["client_fit_gaps"]), 1)
        self.assertEqual(payload["client_fit_summary"]["profile_name"], "Async Python buyer")
        self.assertEqual(payload["client_fit_summary"]["status"], "partial_match")
        self.assertEqual(payload["client_fit_summary"]["matching_rows"], 1)
        self.assertEqual(payload["client_fit_summary"]["excluded_rows"], 1)
        self.assertEqual(payload["client_fit_summary"]["gap_counts"]["LANGUAGE_MISMATCH"], 1)
        self.assertEqual(payload["client_fit_gaps"][0]["reference"], "example/toolkit#17")
        self.assertEqual(
            payload["client_fit_gaps"][0]["gap_codes"],
            [
                "LANGUAGE_MISMATCH",
                "OPPORTUNITY_STATE_NOT_ALLOWED",
                "RISK_LEVEL_NOT_ALLOWED",
                "EXCLUDED_RISK_FLAG:spam_attractive",
            ],
        )
        self.assertIn("language outside", payload["client_fit_gaps"][0]["gap_summary"])
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertFalse(payload["requirements"]["github_write_permission_required"])

    def test_funded_issues_shortlist_profile_can_exclude_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.funded_issues.client_profile.v1",
                        "name": "High threshold Python buyer",
                        "languages": ["python"],
                        "min_usd": 1000,
                        "allowed_opportunity_states": ["active"],
                        "allowed_risk_levels": ["low"],
                        "excluded_risk_flags": [],
                        "read_only": True,
                    }
                ),
                encoding="utf-8",
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "shortlist",
                    "--source",
                    "examples/funded-issues-readonly/issues.json",
                    "--profile",
                    str(profile),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["filters"]["profile"]["name"], "High threshold Python buyer")
        self.assertEqual(payload["summary"]["in_scope"], 0)
        self.assertEqual(payload["summary"]["total_scored"], 0)
        self.assertEqual(payload["shortlist"], [])
        self.assertEqual(payload["no_go_evidence"], [])
        self.assertEqual(len(payload["client_fit_gaps"]), 2)
        self.assertEqual(payload["client_fit_summary"]["status"], "no_matching_rows")
        self.assertEqual(payload["client_fit_summary"]["matching_rows"], 0)
        self.assertEqual(payload["client_fit_summary"]["excluded_rows"], 2)
        self.assertIn(
            "Do not pitch this batch",
            payload["client_fit_summary"]["recommended_action"],
        )
        self.assertEqual(payload["client_fit_gaps"][0]["reference"], "example/project#42")
        self.assertEqual(
            payload["client_fit_gaps"][0]["gap_codes"],
            ["FUNDING_BELOW_MIN_USD"],
        )
        self.assertEqual(payload["delivery_budget"]["suggested_package"], "none")

    def test_funded_issues_shortlist_rejects_invalid_limit(self) -> None:
        proc = run_patchrail(
            [
                "funded-issues",
                "shortlist",
                "--source",
                "examples/funded-issues-readonly/issues.json",
                "--limit",
                "0",
            ]
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("limit must be >= 1", proc.stderr)

    def test_funded_issues_readonly_demo_has_stable_summary(self) -> None:
        expected = json.loads(
            Path("examples/funded-issues-readonly/demo-summary.expected.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    "examples/funded-issues-readonly/run_demo.py",
                    "--output",
                    tmp,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads((Path(tmp) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary, expected)

            for artifact in expected["artifact_files"]:
                self.assertTrue((Path(tmp) / artifact).exists())

            safe_list = json.loads((Path(tmp) / "safe-list.json").read_text(encoding="utf-8"))
            all_issues = json.loads((Path(tmp) / "all-issues.json").read_text(encoding="utf-8"))
            risky = json.loads((Path(tmp) / "risky-explain.json").read_text(encoding="utf-8"))
            safe_explain = (Path(tmp) / "safe-explain.md").read_text(encoding="utf-8")

        self.assertEqual(safe_list["total_returned"], 1)
        self.assertEqual(all_issues["total_returned"], 2)
        self.assertEqual(risky["issue"]["risk_level"], "high")
        self.assertIn("automatic_claims", risky["ethics"]["blocked"])
        self.assertIn("automatic_issue_comments", risky["ethics"]["blocked"])
        self.assertIn("Safe to keep in a local funded-maintenance shortlist", safe_explain)
        self.assertFalse(summary["requirements"]["network_required"])
        self.assertFalse(summary["requirements"]["github_write_permission_required"])


if __name__ == "__main__":
    unittest.main()
