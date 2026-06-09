from __future__ import annotations

import unittest

from patchrail.funded_issues import (
    TESTABILITY_BATCH_SCHEMA_VERSION,
    TESTABILITY_SIGNAL_SCHEMA_VERSION,
    FundedIssue,
    assess_issue_testability,
    assess_testability_batch,
    score_funded_issues,
)


class AssessIssueTestabilityTests(unittest.TestCase):
    def test_failing_test_alone_is_verifiable(self) -> None:
        signal = assess_issue_testability(has_failing_test=True)
        self.assertEqual(signal["schema_version"], TESTABILITY_SIGNAL_SCHEMA_VERSION)
        self.assertTrue(signal["read_only"])
        self.assertEqual(signal["level"], "verifiable")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["VERIFIABLE_TEST_PATH"])
        self.assertEqual(signal["observed"]["present_signal_count"], 1)

    def test_repro_plus_diagnostics_is_verifiable(self) -> None:
        signal = assess_issue_testability(
            has_reproduction_steps=True,
            has_stack_trace_or_logs=True,
        )
        self.assertEqual(signal["level"], "verifiable")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["VERIFIABLE_TEST_PATH"])

    def test_repro_only_is_partially_verifiable(self) -> None:
        signal = assess_issue_testability(
            has_reproduction_steps=True,
            has_stack_trace_or_logs=False,
            has_expected_vs_actual=False,
        )
        self.assertEqual(signal["level"], "partially_verifiable")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["PARTIAL_TEST_PATH"])

    def test_diagnostics_only_is_partially_verifiable(self) -> None:
        signal = assess_issue_testability(has_expected_vs_actual=True)
        self.assertEqual(signal["level"], "partially_verifiable")
        self.assertEqual(signal["reason_codes"], ["PARTIAL_TEST_PATH"])

    def test_all_signals_absent_is_unverifiable_and_flags(self) -> None:
        signal = assess_issue_testability(
            has_failing_test=False,
            has_reproduction_steps=False,
            has_stack_trace_or_logs=False,
            has_expected_vs_actual=False,
        )
        self.assertEqual(signal["level"], "unverifiable")
        self.assertEqual(signal["risk_flags"], ["no_repro_or_test_path"])
        self.assertEqual(signal["reason_codes"], ["NO_REPRO_OR_TEST_PATH"])
        self.assertEqual(signal["observed"]["present_signal_count"], 0)

    def test_no_signals_is_unknown_without_flag(self) -> None:
        signal = assess_issue_testability()
        self.assertEqual(signal["level"], "unknown")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["TESTABILITY_UNVERIFIED"])
        self.assertEqual(signal["observed"]["known_signal_count"], 0)

    def test_failing_test_overrides_other_absent_signals(self) -> None:
        signal = assess_issue_testability(
            has_failing_test=True,
            has_reproduction_steps=False,
            has_stack_trace_or_logs=False,
        )
        self.assertEqual(signal["level"], "verifiable")

    def test_non_boolean_signal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_issue_testability(has_failing_test="yes")  # type: ignore[arg-type]


class TestabilityFlagScoringIntegrationTests(unittest.TestCase):
    def _issue(self, risk_flags: list[str]) -> FundedIssue:
        return FundedIssue(
            id="acme-1",
            platform="github",
            repository="acme/widgets",
            issue_number=42,
            title="Fix flaky integration test",
            url="https://github.com/acme/widgets/issues/42",
            funding_amount=1500.0,
            funding_currency="USD",
            language="python",
            contribution_signals=["reproduction_steps"],
            risk_flags=risk_flags,
            contribution_guidelines_url="https://github.com/acme/widgets/CONTRIBUTING.md",
            opportunity_state="active",
        )

    def test_unverifiable_flag_emits_curated_code_without_forcing_high_risk(self) -> None:
        derived = assess_issue_testability(
            has_failing_test=False,
            has_reproduction_steps=False,
            has_stack_trace_or_logs=False,
            has_expected_vs_actual=False,
        )
        issue = self._issue(derived["risk_flags"])
        row = score_funded_issues([issue])["scores"][0]
        self.assertIn("NO_REPRO_OR_TEST_PATH", row["reason_codes"])
        self.assertEqual(row["issue"]["risk_level"], "low")
        self.assertNotEqual(row["rating"], "no_go")

    def test_unverifiable_flag_lowers_score_versus_unflagged_issue(self) -> None:
        clean = score_funded_issues([self._issue([])])["scores"][0]["score"]
        flagged = score_funded_issues([self._issue(["no_repro_or_test_path"])])["scores"][0][
            "score"
        ]
        self.assertLess(flagged, clean)


class AssessTestabilityBatchTests(unittest.TestCase):
    def _observations(self) -> list[dict[str, object]]:
        return [
            {
                "reference": "verifiable/repo#1",
                "has_failing_test": True,
                "has_reproduction_steps": True,
            },
            {
                "reference": "partial/repo#2",
                "has_reproduction_steps": True,
            },
            {
                "reference": "unverifiable/repo#3",
                "has_failing_test": False,
                "has_reproduction_steps": False,
                "has_stack_trace_or_logs": False,
                "has_expected_vs_actual": False,
            },
            {
                "reference": "unknown/repo#4",
            },
        ]

    def test_batch_payload_shape_and_summary(self) -> None:
        payload = assess_testability_batch(self._observations())
        self.assertEqual(payload["schema_version"], TESTABILITY_BATCH_SCHEMA_VERSION)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["reviewed"], 4)
        summary = payload["summary"]
        self.assertEqual(summary["reviewed"], 4)
        self.assertEqual(summary["verifiable"], 1)
        self.assertEqual(summary["partially_verifiable"], 1)
        self.assertEqual(summary["unverifiable"], 1)
        self.assertEqual(summary["unknown"], 1)
        self.assertIn("automatic_claims", payload["blocked_actions"])

    def test_results_are_sorted_least_verifiable_first(self) -> None:
        payload = assess_testability_batch(self._observations())
        references = [row["reference"] for row in payload["results"]]
        self.assertEqual(
            references,
            ["unverifiable/repo#3", "partial/repo#2", "unknown/repo#4", "verifiable/repo#1"],
        )
        self.assertEqual(payload["results"][0]["level"], "unverifiable")
        self.assertEqual(payload["results"][-1]["level"], "verifiable")

    def test_missing_reference_gets_positional_label(self) -> None:
        payload = assess_testability_batch([{"has_failing_test": True}])
        self.assertEqual(payload["results"][0]["reference"], "observation-1")

    def test_id_and_url_are_accepted_as_reference_fallbacks(self) -> None:
        payload = assess_testability_batch(
            [
                {"id": "polar-7", "has_failing_test": True},
                {"url": "https://example.com/issues/9", "has_failing_test": True},
            ]
        )
        references = {row["reference"] for row in payload["results"]}
        self.assertIn("polar-7", references)
        self.assertIn("https://example.com/issues/9", references)

    def test_empty_batch_is_valid(self) -> None:
        payload = assess_testability_batch([])
        self.assertEqual(payload["reviewed"], 0)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["summary"]["unverifiable"], 0)

    def test_non_list_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_testability_batch({"observations": []})

    def test_non_dict_observation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_testability_batch([{"has_failing_test": True}, "nope"])

    def test_non_string_reference_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_testability_batch([{"reference": 7, "has_failing_test": True}])

    def test_invalid_signal_propagates_validation_error(self) -> None:
        with self.assertRaises(ValueError):
            assess_testability_batch([{"has_failing_test": "maybe"}])


if __name__ == "__main__":
    unittest.main()
