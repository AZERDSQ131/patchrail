from __future__ import annotations

import unittest

from patchrail.funded_issues import (
    STALENESS_BATCH_SCHEMA_VERSION,
    STALENESS_SIGNAL_SCHEMA_VERSION,
    FundedIssue,
    assess_issue_staleness,
    assess_staleness_batch,
    score_funded_issues,
)


class AssessIssueStalenessTests(unittest.TestCase):
    def test_recent_activity_is_active_without_flags(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=4, days_since_created=30)
        self.assertEqual(signal["schema_version"], STALENESS_SIGNAL_SCHEMA_VERSION)
        self.assertTrue(signal["read_only"])
        self.assertEqual(signal["level"], "active")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["RECENT_PUBLIC_ACTIVITY"])
        self.assertEqual(signal["recommended_opportunity_state"], "active")
        self.assertFalse(signal["observed"]["long_unresolved"])

    def test_aging_emits_soft_non_high_risk_flag(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=60)
        self.assertEqual(signal["level"], "aging")
        self.assertEqual(signal["risk_flags"], ["aging_low_activity"])
        self.assertEqual(signal["reason_codes"], ["AGING_LOW_ACTIVITY"])
        self.assertEqual(signal["recommended_opportunity_state"], "active")

    def test_stale_emits_high_risk_flag_and_stale_state(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=140)
        self.assertEqual(signal["level"], "stale")
        self.assertEqual(signal["risk_flags"], ["stale_no_maintainer_signal"])
        self.assertEqual(signal["reason_codes"], ["STALE_NO_MAINTAINER_SIGNAL"])
        self.assertEqual(signal["recommended_opportunity_state"], "stale")

    def test_dormant_emits_high_risk_flag_and_stale_state(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=430, days_since_created=620)
        self.assertEqual(signal["level"], "dormant")
        self.assertEqual(signal["risk_flags"], ["stale_no_maintainer_signal"])
        self.assertEqual(signal["recommended_opportunity_state"], "stale")
        self.assertTrue(signal["observed"]["long_unresolved"])

    def test_engaged_maintainer_softens_stale_to_aging(self) -> None:
        signal = assess_issue_staleness(
            days_since_last_activity=140, maintainer_recently_active=True
        )
        self.assertEqual(signal["level"], "aging")
        self.assertEqual(signal["risk_flags"], ["aging_low_activity"])

    def test_engaged_maintainer_softens_dormant_to_stale(self) -> None:
        signal = assess_issue_staleness(
            days_since_last_activity=430, maintainer_recently_active=True
        )
        self.assertEqual(signal["level"], "stale")
        self.assertEqual(signal["risk_flags"], ["stale_no_maintainer_signal"])

    def test_absent_maintainer_hardens_active_to_aging(self) -> None:
        signal = assess_issue_staleness(
            days_since_last_activity=20, maintainer_recently_active=False
        )
        self.assertEqual(signal["level"], "aging")
        self.assertEqual(signal["risk_flags"], ["aging_low_activity"])

    def test_absent_maintainer_hardens_aging_to_stale(self) -> None:
        signal = assess_issue_staleness(
            days_since_last_activity=60, maintainer_recently_active=False
        )
        self.assertEqual(signal["level"], "stale")
        self.assertEqual(signal["risk_flags"], ["stale_no_maintainer_signal"])

    def test_missing_activity_is_unknown(self) -> None:
        signal = assess_issue_staleness()
        self.assertEqual(signal["level"], "unknown")
        self.assertEqual(signal["risk_flags"], [])
        self.assertEqual(signal["reason_codes"], ["STALENESS_UNVERIFIED"])
        self.assertEqual(signal["recommended_opportunity_state"], "unknown")

    def test_unknown_ignores_maintainer_signal(self) -> None:
        signal = assess_issue_staleness(maintainer_recently_active=True)
        self.assertEqual(signal["level"], "unknown")
        self.assertEqual(signal["recommended_opportunity_state"], "unknown")

    def test_long_unresolved_only_set_when_created_age_known(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=10)
        self.assertFalse(signal["observed"]["long_unresolved"])
        aged = assess_issue_staleness(days_since_last_activity=10, days_since_created=365)
        self.assertTrue(aged["observed"]["long_unresolved"])

    def test_thresholds_are_echoed(self) -> None:
        signal = assess_issue_staleness(days_since_last_activity=10)
        self.assertEqual(signal["thresholds"]["active_max_days"], 30)
        self.assertEqual(signal["thresholds"]["stale_max_days"], 180)

    def test_negative_days_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_issue_staleness(days_since_last_activity=-1)

    def test_boolean_days_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_issue_staleness(days_since_last_activity=True)

    def test_float_days_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_issue_staleness(days_since_last_activity=12.5)  # type: ignore[arg-type]

    def test_non_boolean_maintainer_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_issue_staleness(
                days_since_last_activity=10,
                maintainer_recently_active="yes",  # type: ignore[arg-type]
            )


class StalenessFlagScoringIntegrationTests(unittest.TestCase):
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

    def test_stale_flag_forces_high_risk_no_go(self) -> None:
        derived = assess_issue_staleness(days_since_last_activity=200)
        issue = self._issue(derived["risk_flags"])
        row = score_funded_issues([issue])["scores"][0]
        self.assertEqual(issue.risk_level, "high")
        self.assertEqual(row["rating"], "no_go")
        self.assertIn("STALE_NO_MAINTAINER_SIGNAL", row["reason_codes"])

    def test_aging_flag_costs_score_without_forcing_high_risk(self) -> None:
        derived = assess_issue_staleness(days_since_last_activity=60)
        issue = self._issue(derived["risk_flags"])
        row = score_funded_issues([issue])["scores"][0]
        self.assertEqual(issue.risk_level, "low")
        self.assertIn("AGING_LOW_ACTIVITY", row["reason_codes"])

    def test_aging_flag_lowers_score_versus_unflagged_issue(self) -> None:
        clean = score_funded_issues([self._issue([])])["scores"][0]["score"]
        flagged = score_funded_issues([self._issue(["aging_low_activity"])])["scores"][0]["score"]
        self.assertLess(flagged, clean)


class AssessStalenessBatchTests(unittest.TestCase):
    def _observations(self) -> list[dict[str, object]]:
        return [
            {"reference": "fresh/repo#1", "days_since_last_activity": 5},
            {"reference": "dormant/repo#2", "days_since_last_activity": 400},
            {"reference": "stale/repo#3", "days_since_last_activity": 150},
            {"reference": "aging/repo#4", "days_since_last_activity": 60},
        ]

    def test_batch_payload_shape_and_summary(self) -> None:
        payload = assess_staleness_batch(self._observations())
        self.assertEqual(payload["schema_version"], STALENESS_BATCH_SCHEMA_VERSION)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["reviewed"], 4)
        summary = payload["summary"]
        self.assertEqual(summary["reviewed"], 4)
        self.assertEqual(summary["active"], 1)
        self.assertEqual(summary["aging"], 1)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual(summary["dormant"], 1)
        self.assertEqual(summary["stale_or_dormant"], 2)
        self.assertIn("automatic_claims", payload["blocked_actions"])

    def test_results_sorted_most_stale_first(self) -> None:
        payload = assess_staleness_batch(self._observations())
        references = [row["reference"] for row in payload["results"]]
        self.assertEqual(
            references, ["dormant/repo#2", "stale/repo#3", "aging/repo#4", "fresh/repo#1"]
        )
        self.assertEqual(payload["results"][0]["level"], "dormant")
        self.assertEqual(payload["results"][-1]["level"], "active")

    def test_missing_reference_gets_positional_label(self) -> None:
        payload = assess_staleness_batch([{"days_since_last_activity": 5}])
        self.assertEqual(payload["results"][0]["reference"], "observation-1")

    def test_id_and_url_are_accepted_as_reference_fallbacks(self) -> None:
        payload = assess_staleness_batch(
            [
                {"id": "polar-7", "days_since_last_activity": 5},
                {"url": "https://example.com/issues/9", "days_since_last_activity": 5},
            ]
        )
        references = {row["reference"] for row in payload["results"]}
        self.assertEqual(references, {"polar-7", "https://example.com/issues/9"})

    def test_unknown_observations_are_counted(self) -> None:
        payload = assess_staleness_batch([{"reference": "mystery/repo#9"}])
        self.assertEqual(payload["summary"]["unknown"], 1)
        self.assertEqual(payload["results"][0]["level"], "unknown")

    def test_non_list_observations_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_staleness_batch({"days_since_last_activity": 5})

    def test_non_object_observation_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_staleness_batch([5])

    def test_non_string_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_staleness_batch([{"reference": 7, "days_since_last_activity": 5}])


if __name__ == "__main__":
    unittest.main()
