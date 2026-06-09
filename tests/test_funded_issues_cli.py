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
        self.assertIn("paid scope", proc.stdout)
        self.assertIn("## No-Go Moat", proc.stdout)
        self.assertIn("High-risk or excluded | 1", proc.stdout)
        self.assertIn("Stale or closed | 1", proc.stdout)
        self.assertIn("### Opportunity States", proc.stdout)
        self.assertIn("`active`: `1`", proc.stdout)
        self.assertIn("example/project#42", proc.stdout)
        self.assertNotIn("example/toolkit#17", proc.stdout)
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

                blocked_actions = schema["$defs"]["blocked_actions"]["items"]["enum"]
                self.assertIn("automatic_claims", blocked_actions)
                self.assertIn("automatic_pull_requests", blocked_actions)
                self.assertIn("automatic_issue_comments", blocked_actions)
                self.assertIn("mass_outreach", blocked_actions)
                self.assertIn("ranking_by_money_only", blocked_actions)

                if schema_name == "funded-issues-shortlist":
                    self.assertIn("decision_summary", schema["required"])
                    self.assertIn("delivery_budget", schema["required"])
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
                        "needs_funding_verification",
                        schema["$defs"]["scored_issue"]["properties"]["decision_gate"]["enum"],
                    )
                else:
                    self.assertIn("decision_summary", schema["required"])
                    self.assertIn("delivery_budget", schema["required"])
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
