from __future__ import annotations

import unittest

from patchrail.funded_issues import (
    PAYOUT_EFFORT_BATCH_SCHEMA_VERSION,
    PAYOUT_EFFORT_SIGNAL_SCHEMA_VERSION,
    FundedIssue,
    assess_payout_effort,
    assess_payout_effort_batch,
    score_funded_issues,
)


class AssessPayoutEffortTests(unittest.TestCase):
    def test_proportionate_payout_is_strong(self) -> None:
        signal = assess_payout_effort(
            funding_amount=2400,
            funding_currency="USD",
            estimated_effort_hours=12,
        )
        self.assertEqual(signal["schema_version"], PAYOUT_EFFORT_SIGNAL_SCHEMA_VERSION)
        self.assertTrue(signal["read_only"])
        self.assertEqual(signal["level"], "strong")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["PAYOUT_PROPORTIONATE_TO_EFFORT"])
        self.assertEqual(signal["observed"]["effective_hourly_rate"], 200.0)
        self.assertGreaterEqual(signal["observed"]["payout_effort_ratio"], 1.0)

    def test_near_floor_payout_is_marginal_without_flag(self) -> None:
        signal = assess_payout_effort(
            funding_amount=900,
            funding_currency="USD",
            estimated_effort_hours=8,
        )
        self.assertEqual(signal["level"], "marginal")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["PAYOUT_NEAR_EFFORT_FLOOR"])
        self.assertEqual(signal["observed"]["effective_hourly_rate"], 112.5)

    def test_underpaid_bounty_flags_payout_too_low(self) -> None:
        signal = assess_payout_effort(
            funding_amount=250,
            funding_currency="USD",
            estimated_effort_hours=10,
        )
        self.assertEqual(signal["level"], "low")
        self.assertEqual(signal["risk_flags"], ["payout_too_low_for_effort"])
        self.assertEqual(signal["reason_codes"], ["PAYOUT_TOO_LOW_FOR_EFFORT"])
        self.assertEqual(signal["observed"]["effective_hourly_rate"], 25.0)

    def test_missing_funding_is_unknown(self) -> None:
        signal = assess_payout_effort(estimated_effort_hours=4)
        self.assertEqual(signal["level"], "unknown")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["FUNDING_STATE_UNCLEAR"])
        self.assertIsNone(signal["observed"]["payout_effort_ratio"])

    def test_missing_effort_is_unknown(self) -> None:
        signal = assess_payout_effort(funding_amount=1000)
        self.assertEqual(signal["level"], "unknown")
        self.assertIsNone(signal["observed"]["effective_hourly_rate"])

    def test_non_usd_currency_is_unverified(self) -> None:
        signal = assess_payout_effort(
            funding_amount=500,
            funding_currency="EUR",
            estimated_effort_hours=4,
        )
        self.assertEqual(signal["level"], "unverified_currency")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["PAYOUT_CURRENCY_UNVERIFIED"])
        self.assertIsNone(signal["observed"]["payout_effort_ratio"])
        self.assertEqual(signal["observed"]["funding_currency"], "EUR")

    def test_custom_target_rate_is_echoed_and_used(self) -> None:
        signal = assess_payout_effort(
            funding_amount=600,
            funding_currency="USD",
            estimated_effort_hours=6,
            target_hourly_rate_usd=50,
        )
        self.assertEqual(signal["thresholds"]["target_hourly_rate_usd"], 50.0)
        self.assertEqual(signal["level"], "strong")
        self.assertEqual(signal["observed"]["payout_effort_ratio"], 2.0)

    def test_negative_amount_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort(funding_amount=-5, estimated_effort_hours=1)

    def test_zero_effort_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort(funding_amount=100, estimated_effort_hours=0)

    def test_boolean_amount_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort(funding_amount=True, estimated_effort_hours=1)

    def test_non_numeric_effort_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort(
                funding_amount=100,
                estimated_effort_hours="lots",  # type: ignore[arg-type]
            )


class PayoutEffortFlagScoringIntegrationTests(unittest.TestCase):
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

    def test_payout_flag_emits_curated_code_without_forcing_high_risk(self) -> None:
        derived = assess_payout_effort(
            funding_amount=250,
            funding_currency="USD",
            estimated_effort_hours=10,
        )
        issue = self._issue(derived["risk_flags"])
        row = score_funded_issues([issue])["scores"][0]
        self.assertIn("PAYOUT_TOO_LOW_FOR_EFFORT", row["reason_codes"])
        self.assertEqual(row["issue"]["risk_level"], "low")
        self.assertLess(row["score"], 100)

    def test_payout_flag_lowers_score_versus_unflagged_issue(self) -> None:
        clean = score_funded_issues([self._issue([])])["scores"][0]["score"]
        flagged = score_funded_issues(
            [self._issue(["payout_too_low_for_effort"])]
        )["scores"][0]["score"]
        self.assertLess(flagged, clean)


class AssessPayoutEffortBatchTests(unittest.TestCase):
    def _observations(self) -> list[dict[str, object]]:
        return [
            {
                "reference": "good/repo#1",
                "funding_amount": 2400,
                "estimated_effort_hours": 12,
            },
            {
                "reference": "underpaid/repo#2",
                "funding_amount": 250,
                "estimated_effort_hours": 10,
            },
            {
                "reference": "marginal/repo#3",
                "funding_amount": 900,
                "estimated_effort_hours": 8,
            },
        ]

    def test_batch_payload_shape_and_summary(self) -> None:
        payload = assess_payout_effort_batch(self._observations())
        self.assertEqual(payload["schema_version"], PAYOUT_EFFORT_BATCH_SCHEMA_VERSION)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["reviewed"], 3)
        summary = payload["summary"]
        self.assertEqual(summary["reviewed"], 3)
        self.assertEqual(summary["low"], 1)
        self.assertEqual(summary["marginal"], 1)
        self.assertEqual(summary["strong"], 1)
        self.assertEqual(summary["underpaid"], 1)
        self.assertIn("automatic_claims", payload["blocked_actions"])

    def test_results_are_sorted_worst_payout_first(self) -> None:
        payload = assess_payout_effort_batch(self._observations())
        references = [row["reference"] for row in payload["results"]]
        self.assertEqual(
            references, ["underpaid/repo#2", "marginal/repo#3", "good/repo#1"]
        )
        self.assertEqual(payload["results"][0]["level"], "low")
        self.assertEqual(payload["results"][-1]["level"], "strong")

    def test_missing_reference_gets_positional_label(self) -> None:
        payload = assess_payout_effort_batch(
            [{"funding_amount": 100, "estimated_effort_hours": 1}]
        )
        self.assertEqual(payload["results"][0]["reference"], "observation-1")

    def test_id_and_url_are_accepted_as_reference_fallbacks(self) -> None:
        payload = assess_payout_effort_batch(
            [
                {"id": "polar-7", "funding_amount": 100, "estimated_effort_hours": 1},
                {
                    "url": "https://example.com/issues/9",
                    "funding_amount": 100,
                    "estimated_effort_hours": 1,
                },
            ]
        )
        references = {row["reference"] for row in payload["results"]}
        self.assertIn("polar-7", references)
        self.assertIn("https://example.com/issues/9", references)

    def test_empty_batch_is_valid(self) -> None:
        payload = assess_payout_effort_batch([])
        self.assertEqual(payload["reviewed"], 0)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["summary"]["underpaid"], 0)

    def test_non_list_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort_batch({"observations": []})

    def test_non_dict_observation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort_batch(
                [{"funding_amount": 1, "estimated_effort_hours": 1}, "nope"]
            )

    def test_non_string_reference_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort_batch(
                [{"reference": 7, "funding_amount": 1, "estimated_effort_hours": 1}]
            )

    def test_invalid_amount_propagates_validation_error(self) -> None:
        with self.assertRaises(ValueError):
            assess_payout_effort_batch([{"funding_amount": -1, "estimated_effort_hours": 1}])


if __name__ == "__main__":
    unittest.main()
