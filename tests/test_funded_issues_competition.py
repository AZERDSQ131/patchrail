from __future__ import annotations

import unittest

from patchrail.funded_issues import (
    COMPETITION_SIGNAL_SCHEMA_VERSION,
    FundedIssue,
    assess_bounty_competition,
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


if __name__ == "__main__":
    unittest.main()
