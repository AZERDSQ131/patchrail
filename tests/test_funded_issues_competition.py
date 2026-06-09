from __future__ import annotations

import unittest

from patchrail.funded_issues import (
    COMPETITION_BATCH_SCHEMA_VERSION,
    COMPETITION_SIGNAL_SCHEMA_VERSION,
    FundedIssue,
    assess_bounty_competition,
    assess_competition_batch,
    score_funded_issues,
)


class AssessBountyCompetitionTests(unittest.TestCase):
    def test_quiet_issue_has_no_competition_pressure(self) -> None:
        signal = assess_bounty_competition(
            competing_pr_count=1,
            distinct_claimants=1,
            comment_count=4,
            assigned=False,
        )
        self.assertEqual(signal["schema_version"], COMPETITION_SIGNAL_SCHEMA_VERSION)
        self.assertTrue(signal["read_only"])
        self.assertEqual(signal["level"], "low")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["NO_COMPETITION_PRESSURE"])

    def test_many_competing_prs_flags_contested(self) -> None:
        signal = assess_bounty_competition(competing_pr_count=4, assigned=True)
        self.assertIn("contested_bounty", signal["risk_flags"])
        self.assertIn("CONTESTED_HIGH_COMPETITION", signal["reason_codes"])
        # assigned suppresses the crowded-no-owner flag even with competing PRs.
        self.assertNotIn("crowded_no_assignment", signal["risk_flags"])
        self.assertEqual(signal["level"], "elevated")

    def test_many_distinct_claimants_flags_contested(self) -> None:
        signal = assess_bounty_competition(distinct_claimants=3, assigned=True)
        self.assertIn("contested_bounty", signal["risk_flags"])

    def test_busy_unassigned_issue_flags_crowded_no_owner(self) -> None:
        signal = assess_bounty_competition(comment_count=15, assigned=False)
        self.assertIn("crowded_no_assignment", signal["risk_flags"])
        self.assertIn("CROWDED_NO_CLEAR_OWNER", signal["reason_codes"])
        self.assertNotIn("contested_bounty", signal["risk_flags"])
        self.assertEqual(signal["level"], "elevated")

    def test_assignment_suppresses_crowded_flag(self) -> None:
        signal = assess_bounty_competition(comment_count=40, assigned=True)
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["level"], "low")

    def test_contested_and_crowded_is_high_noise_trap(self) -> None:
        signal = assess_bounty_competition(
            competing_pr_count=5,
            distinct_claimants=4,
            comment_count=22,
            assigned=False,
        )
        self.assertEqual(signal["level"], "high")
        self.assertEqual(
            sorted(signal["risk_flags"]),
            ["contested_bounty", "crowded_no_assignment"],
        )
        self.assertIn("noise trap", signal["recommended_next_step"])

    def test_observed_and_thresholds_are_echoed(self) -> None:
        signal = assess_bounty_competition(competing_pr_count=2, comment_count=7)
        self.assertEqual(signal["observed"]["competing_pr_count"], 2)
        self.assertEqual(signal["observed"]["comment_count"], 7)
        self.assertEqual(signal["thresholds"]["competing_pr_count_contested"], 3)

    def test_negative_counts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_bounty_competition(competing_pr_count=-1)

    def test_boolean_is_not_accepted_as_a_count(self) -> None:
        with self.assertRaises(ValueError):
            assess_bounty_competition(comment_count=True)

    def test_non_integer_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_bounty_competition(distinct_claimants=2.5)  # type: ignore[arg-type]

    def test_non_boolean_assigned_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_bounty_competition(assigned="yes")  # type: ignore[arg-type]


class CompetitionFlagScoringIntegrationTests(unittest.TestCase):
    def _issue(self, risk_flags: list[str]) -> FundedIssue:
        return FundedIssue(
            id="acme-1",
            platform="github",
            repository="acme/widgets",
            issue_number=42,
            title="Fix flaky integration test",
            url="https://github.com/acme/widgets/issues/42",
            funding_amount=500.0,
            funding_currency="USD",
            language="python",
            contribution_signals=["reproduction_steps"],
            risk_flags=risk_flags,
            contribution_guidelines_url="https://github.com/acme/widgets/CONTRIBUTING.md",
            opportunity_state="active",
        )

    def test_competition_flags_emit_curated_reason_codes_without_forcing_high_risk(self) -> None:
        derived = assess_bounty_competition(
            competing_pr_count=6,
            distinct_claimants=5,
            comment_count=30,
            assigned=False,
        )
        issue = self._issue(derived["risk_flags"])
        payload = score_funded_issues([issue])
        row = payload["scores"][0]

        self.assertIn("CONTESTED_HIGH_COMPETITION", row["reason_codes"])
        self.assertIn("CROWDED_NO_CLEAR_OWNER", row["reason_codes"])
        # Competition flags cost score but do not auto-escalate to high risk.
        self.assertEqual(row["issue"]["risk_level"], "low")
        self.assertLess(row["score"], 100)

    def test_competition_flags_lower_score_versus_quiet_issue(self) -> None:
        quiet = score_funded_issues([self._issue([])])["scores"][0]["score"]
        contested = score_funded_issues(
            [self._issue(["contested_bounty", "crowded_no_assignment"])]
        )["scores"][0]["score"]
        self.assertLess(contested, quiet)


class AssessCompetitionBatchTests(unittest.TestCase):
    def _observations(self) -> list[dict[str, object]]:
        return [
            {"reference": "quiet/repo#1", "competing_pr_count": 1, "comment_count": 3},
            {
                "reference": "trap/repo#2",
                "competing_pr_count": 6,
                "distinct_claimants": 5,
                "comment_count": 30,
                "assigned": False,
            },
            {
                "reference": "busy/repo#3",
                "comment_count": 18,
                "assigned": False,
            },
        ]

    def test_batch_payload_shape_and_summary(self) -> None:
        payload = assess_competition_batch(self._observations())
        self.assertEqual(payload["schema_version"], COMPETITION_BATCH_SCHEMA_VERSION)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["reviewed"], 3)
        summary = payload["summary"]
        self.assertEqual(summary["reviewed"], 3)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(summary["elevated"], 1)
        self.assertEqual(summary["low"], 1)
        self.assertEqual(summary["noise_traps"], 2)
        self.assertEqual(summary["contested_bounty"], 1)
        self.assertEqual(summary["crowded_no_assignment"], 2)
        self.assertIn("automatic_claims", payload["blocked_actions"])

    def test_results_are_sorted_highest_pressure_first(self) -> None:
        payload = assess_competition_batch(self._observations())
        references = [row["reference"] for row in payload["results"]]
        self.assertEqual(references, ["trap/repo#2", "busy/repo#3", "quiet/repo#1"])
        self.assertEqual(payload["results"][0]["level"], "high")
        self.assertEqual(payload["results"][-1]["level"], "low")

    def test_missing_reference_gets_positional_label(self) -> None:
        payload = assess_competition_batch([{"comment_count": 1}])
        self.assertEqual(payload["results"][0]["reference"], "observation-1")

    def test_id_and_url_are_accepted_as_reference_fallbacks(self) -> None:
        payload = assess_competition_batch(
            [
                {"id": "polar-7", "comment_count": 1},
                {"url": "https://example.com/issues/9", "comment_count": 1},
            ]
        )
        references = {row["reference"] for row in payload["results"]}
        self.assertIn("polar-7", references)
        self.assertIn("https://example.com/issues/9", references)

    def test_empty_batch_is_valid(self) -> None:
        payload = assess_competition_batch([])
        self.assertEqual(payload["reviewed"], 0)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["summary"]["noise_traps"], 0)

    def test_non_list_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_competition_batch({"observations": []})

    def test_non_dict_observation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_competition_batch([{"comment_count": 1}, "nope"])

    def test_non_string_reference_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_competition_batch([{"reference": 7, "comment_count": 1}])

    def test_invalid_count_propagates_validation_error(self) -> None:
        with self.assertRaises(ValueError):
            assess_competition_batch([{"competing_pr_count": -1}])


if __name__ == "__main__":
    unittest.main()
