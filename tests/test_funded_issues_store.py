from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchrail.funded_issues.discovery import FundedIssue
from patchrail.funded_issues.store import (
    FRESH_SCHEMA_VERSION,
    STORE_SCHEMA_VERSION,
    STORE_STATUS_SCHEMA_VERSION,
    empty_store,
    fresh_issues,
    load_store,
    merge_into_store,
    save_store,
    store_status,
)

NOW_1 = "2026-06-09T12:00:00Z"
NOW_2 = "2026-06-09T18:00:00Z"
NOW_3 = "2026-06-10T18:00:00Z"


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _issue(
    *,
    url: str = "https://github.com/example/project/issues/42",
    state: str = "active",
    amount: float | None = 250.0,
    currency: str | None = "USD",
) -> FundedIssue:
    return FundedIssue(
        id="example-project-42",
        platform="polar",
        repository="example/project",
        issue_number=42,
        title="Reduce flaky integration test timeout",
        url=url,
        funding_amount=amount,
        funding_currency=currency,
        language="python",
        opportunity_state=state,
        contribution_guidelines_url="https://example.com/CONTRIBUTING.md",
        contribution_signals=["reproduction included"],
    )


class MergeIntoStoreTests(unittest.TestCase):
    def test_new_entry_is_added_with_first_seen(self) -> None:
        store = empty_store()
        summary = merge_into_store(store, [_issue()], NOW_1)

        self.assertEqual(summary.added, 1)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.transitioned, 0)
        self.assertEqual(summary.unchanged, 0)

        entry = store["entries"]["https://github.com/example/project/issues/42"]
        self.assertEqual(entry["first_seen"], NOW_1)
        self.assertEqual(entry["last_seen"], NOW_1)
        self.assertEqual(entry["last_checked"], NOW_1)
        self.assertEqual(entry["state"], "active")
        self.assertEqual(entry["state_history"], [{"state": "active", "at": NOW_1, "from": None}])
        # A bare FundedIssue carries no readiness score; scoring is attached by
        # the CLI track path, not by the store layer.
        self.assertNotIn("score", entry)

    def test_idempotent_merge_changes_only_last_checked_and_last_seen(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue()], NOW_1)
        before = json.loads(json.dumps(store))

        summary = merge_into_store(store, [_issue()], NOW_2)

        self.assertEqual(summary.added, 0)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.transitioned, 0)
        self.assertEqual(summary.unchanged, 1)

        entry = store["entries"]["https://github.com/example/project/issues/42"]
        before_entry = before["entries"]["https://github.com/example/project/issues/42"]
        # Only last_checked / last_seen move; everything else (incl. first_seen,
        # state_history, the issue record) is unchanged.
        self.assertEqual(entry["last_checked"], NOW_2)
        self.assertEqual(entry["last_seen"], NOW_2)
        for key in ("first_seen", "state", "state_history", "issue"):
            self.assertEqual(entry[key], before_entry[key])

    def test_same_now_merge_is_byte_identical(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue()], NOW_1)
        before = json.dumps(store, sort_keys=True)
        merge_into_store(store, [_issue()], NOW_1)
        self.assertEqual(json.dumps(store, sort_keys=True), before)

    def test_state_transition_recorded_exactly_once(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue(state="active")], NOW_1)

        summary = merge_into_store(store, [_issue(state="closed")], NOW_2)
        self.assertEqual(summary.transitioned, 1)
        self.assertEqual(summary.added, 0)
        self.assertEqual(summary.unchanged, 0)
        self.assertEqual(
            summary.transitions,
            [
                {
                    "url": "https://github.com/example/project/issues/42",
                    "state": "closed",
                    "at": NOW_2,
                    "from": "active",
                }
            ],
        )

        entry = store["entries"]["https://github.com/example/project/issues/42"]
        self.assertEqual(entry["state"], "closed")
        self.assertEqual(len(entry["state_history"]), 2)

        # Re-merging the same closed state must NOT append another transition.
        summary = merge_into_store(store, [_issue(state="closed")], NOW_3)
        self.assertEqual(summary.transitioned, 0)
        self.assertEqual(summary.unchanged, 1)
        self.assertEqual(len(entry["state_history"]), 2)

    def test_open_alias_normalizes_to_active(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue(state="open")], NOW_1)
        entry = store["entries"]["https://github.com/example/project/issues/42"]
        self.assertEqual(entry["state"], "active")

    def test_dict_input_with_explicit_score(self) -> None:
        store = empty_store()
        record = _issue().to_dict()
        record["score"] = 91
        summary = merge_into_store(store, [record], NOW_1)
        self.assertEqual(summary.added, 1)
        entry = store["entries"]["https://github.com/example/project/issues/42"]
        self.assertEqual(entry["score"], 91)


class StoreStatusTests(unittest.TestCase):
    def test_status_aggregates_states_usd_and_added_window(self) -> None:
        store = empty_store()
        merge_into_store(
            store,
            [
                _issue(url="https://example.com/a", state="active", amount=250.0, currency="USD"),
                _issue(url="https://example.com/b", state="closed", amount=1500.0, currency="USD"),
                _issue(url="https://example.com/c", state="active", amount=None, currency=None),
            ],
            NOW_1,
        )

        status = store_status(store, "2026-06-09T20:00:00Z")
        self.assertEqual(status["schema_version"], STORE_STATUS_SCHEMA_VERSION)
        self.assertEqual(status["total_entries"], 3)
        self.assertEqual(status["states"], {"active": 2, "closed": 1, "stale": 0, "unknown": 0})
        self.assertEqual(status["added_24h"], 3)
        self.assertEqual(status["total_usd"], 1750.0)
        self.assertEqual(status["usd_entries"], 2)
        self.assertFalse(status["requirements"]["network_required"])

    def test_added_24h_excludes_older_entries(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue(url="https://example.com/old")], NOW_1)
        # 30 hours later, nothing was first seen in the last 24h.
        status = store_status(store, "2026-06-10T18:00:00Z")
        self.assertEqual(status["added_24h"], 0)

    def test_status_without_now_reports_added_none(self) -> None:
        store = empty_store()
        merge_into_store(store, [_issue()], NOW_1)
        status = store_status(store)
        self.assertIsNone(status["added_24h"])
        self.assertIsNone(status["now"])


class LoadSaveStoreTests(unittest.TestCase):
    def test_load_missing_file_returns_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = load_store(Path(tmp) / "absent.json")
            self.assertEqual(store["schema_version"], STORE_SCHEMA_VERSION)
            self.assertEqual(store["entries"], {})

    def test_save_then_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "store.json"
            store = empty_store()
            merge_into_store(store, [_issue()], NOW_1)
            save_store(path, store)
            self.assertTrue(path.exists())
            reloaded = load_store(path)
            self.assertEqual(reloaded["entries"], store["entries"])

    def test_load_rejects_wrong_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            path.write_text(json.dumps({"schema_version": "other", "entries": {}}), "utf-8")
            with self.assertRaises(ValueError):
                load_store(path)


class FundedIssuesTrackCliTests(unittest.TestCase):
    def test_track_then_status_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"

            track = run_patchrail(
                [
                    "funded-issues",
                    "track",
                    "--store",
                    str(store_path),
                    "--input",
                    "examples/funded-issues-readonly/issues.json",
                    "--now",
                    NOW_1,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(track.returncode, 0, track.stderr)
            payload = json.loads(track.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.funded_issues.track.v1")
            self.assertEqual(payload["summary"]["added"], 2)
            self.assertEqual(payload["total_entries"], 2)

            # Store file is valid against its own schema_version.
            saved = json.loads(store_path.read_text("utf-8"))
            self.assertEqual(saved["schema_version"], STORE_SCHEMA_VERSION)
            self.assertTrue(saved["read_only"])

            status = run_patchrail(
                [
                    "funded-issues",
                    "track-status",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-09T20:00:00Z",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["total_entries"], 2)
            self.assertEqual(status_payload["states"]["active"], 1)
            self.assertEqual(status_payload["states"]["closed"], 1)
            self.assertEqual(status_payload["added_24h"], 2)
            self.assertEqual(status_payload["total_usd"], 1750.0)

    def test_track_is_idempotent_except_last_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            args = [
                "funded-issues",
                "track",
                "--store",
                str(store_path),
                "--input",
                "examples/funded-issues-readonly/issues.json",
                "--now",
                NOW_1,
            ]
            self.assertEqual(run_patchrail(args).returncode, 0)
            first = store_path.read_text("utf-8")
            # Same --now: byte-identical file.
            self.assertEqual(run_patchrail(args).returncode, 0)
            self.assertEqual(store_path.read_text("utf-8"), first)

            # New --now: only last_checked / last_seen move.
            args[-1] = NOW_2
            self.assertEqual(run_patchrail(args).returncode, 0)
            before = json.loads(first)
            after = json.loads(store_path.read_text("utf-8"))
            for url, entry in after["entries"].items():
                before_entry = before["entries"][url]
                self.assertEqual(entry["last_checked"], NOW_2)
                self.assertEqual(entry["last_seen"], NOW_2)
                for key in ("first_seen", "state", "state_history", "issue", "score"):
                    self.assertEqual(entry[key], before_entry[key])

    def test_schema_command_exposes_store_contracts(self) -> None:
        expected = {
            "funded-issues-store": "patchrail.funded_issues.store.v1",
            "funded-issues-store-status": "patchrail.funded_issues.store_status.v1",
        }
        for name, version in expected.items():
            with self.subTest(schema=name):
                proc = run_patchrail(["schema", name])
                self.assertEqual(proc.returncode, 0, proc.stderr)
                schema = json.loads(proc.stdout)
                self.assertIn("https://patchrail.dev/schemas/", schema["$id"])
                self.assertEqual(schema["properties"]["schema_version"]["const"], version)
                self.assertEqual(schema["properties"]["read_only"]["const"], True)
                self.assertIn("blocked_actions", schema["required"])
                self.assertIn("requirements", schema["required"])


def _store_entry(
    *,
    url: str,
    repository: str,
    first_seen: str,
    state: str = "active",
    created_at: str | None = None,
    posted_days: int | None = None,
    attempt_count: int | None = None,
    assignee: object | None = None,
    assignees: list | None = None,
    board_org: str | None = None,
    amount: float | None = 150.0,
    currency: str | None = "USD",
) -> dict:
    """Build a raw store entry directly so freshness logic can be exercised
    without round-tripping every optional field through the importers."""
    issue: dict = {
        "url": url,
        "reference": repository + "#1",
        "repository": repository,
        "title": "Fresh bounty",
        "funding": {"amount": amount, "currency": currency, "display": "$150"},
    }
    if created_at is not None:
        issue["metadata"] = {"created_at": created_at}
    if posted_days is not None:
        issue["posted"] = {"approx_days": posted_days, "text": f"{posted_days} days ago"}
    if attempt_count is not None:
        issue["attempt_count"] = attempt_count
    if assignee is not None:
        issue["assignee"] = assignee
    if assignees is not None:
        issue["assignees"] = assignees
    if board_org is not None:
        issue["board"] = {"org": board_org, "source": "algora_board"}
    return {
        "first_seen": first_seen,
        "last_seen": first_seen,
        "last_checked": first_seen,
        "state": state,
        "score": 0,
        "noise_flags": [],
        "issue": issue,
    }


class FreshIssuesTests(unittest.TestCase):
    NOW = "2026-06-11T12:00:00Z"

    def _store(self, *entries: dict) -> dict:
        store = empty_store()
        for entry in entries:
            store["entries"][entry["issue"]["url"]] = entry
        return store

    def test_created_at_within_window_is_fresh(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-01T00:00:00Z",
                created_at="2026-06-10T12:00:00Z",  # 24h before NOW
                attempt_count=2,
            )
        )
        payload = fresh_issues(store, self.NOW, hours=48)
        self.assertEqual(payload["schema_version"], FRESH_SCHEMA_VERSION)
        self.assertEqual(payload["fresh_count"], 1)
        row = payload["fresh"][0]
        self.assertEqual(row["age_basis"], "created_at")
        self.assertEqual(row["age_hours"], 24.0)
        self.assertEqual(row["attempt_count"], 2)
        self.assertEqual(row["org"], "acme")
        self.assertEqual(row["solver_status"], "go_candidate")
        self.assertEqual(row["go_blockers"], [])

    def test_old_created_at_excluded(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T11:00:00Z",  # tracker just saw it...
                created_at="2026-01-01T00:00:00Z",  # ...but bounty is months old
            )
        )
        payload = fresh_issues(store, self.NOW, hours=48)
        self.assertEqual(payload["fresh_count"], 0)

    def test_first_seen_fallback_when_no_date_signal(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/3",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",  # 12h before NOW
            )
        )
        payload = fresh_issues(store, self.NOW, hours=48)
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["age_basis"], "first_seen")

    def test_orders_by_freshness_and_filters_org(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/10",
                repository="acme/repo",
                first_seen="2026-06-01T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",  # 6h
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/11",
                repository="acme/repo",
                first_seen="2026-06-01T00:00:00Z",
                created_at="2026-06-10T18:00:00Z",  # 18h
            ),
            _store_entry(
                url="https://github.com/other/repo/issues/12",
                repository="other/repo",
                first_seen="2026-06-01T00:00:00Z",
                created_at="2026-06-11T11:00:00Z",  # 1h but wrong org
            ),
        )
        payload = fresh_issues(store, self.NOW, hours=48, orgs=["acme"])
        self.assertEqual(payload["fresh_count"], 2)
        ages = [row["age_hours"] for row in payload["fresh"]]
        self.assertEqual(ages, sorted(ages))
        self.assertEqual(payload["orgs"], ["acme"])
        self.assertEqual(payload["sort"], "freshness")

    def test_solver_sort_prioritizes_go_candidates_then_freshness(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/60",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T11:00:00Z",  # 1h but too contested
                attempt_count=9,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/61",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",  # 6h and clean GO
                attempt_count=1,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/62",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T04:00:00Z",  # 8h and needs manual review
                amount=None,
                currency=None,
            ),
        )

        payload = fresh_issues(store, self.NOW, sort_by="solver")

        self.assertEqual(payload["sort"], "solver")
        self.assertEqual(
            [row["url"] for row in payload["fresh"]],
            [
                "https://github.com/acme/repo/issues/61",
                "https://github.com/acme/repo/issues/62",
                "https://github.com/acme/repo/issues/60",
            ],
        )
        self.assertEqual(
            [row["solver_status"] for row in payload["fresh"]],
            ["go_candidate", "needs_review", "no_go"],
        )

    def test_max_rows_limits_after_sort_and_preserves_before_limit_count(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/70",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T10:00:00Z",  # 2h, no-go
                attempt_count=9,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/71",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T08:00:00Z",  # 4h, go candidate
                attempt_count=1,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/72",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T09:00:00Z",  # 3h, needs review
                amount=None,
                currency=None,
            ),
        )

        payload = fresh_issues(store, self.NOW, sort_by="solver", max_rows=2)

        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["fresh_count_before_limit"], 3)
        self.assertEqual(payload["fresh_count"], 2)
        self.assertEqual(
            [row["url"] for row in payload["fresh"]],
            [
                "https://github.com/acme/repo/issues/71",
                "https://github.com/acme/repo/issues/72",
            ],
        )

    def test_invalid_max_rows_raises(self) -> None:
        with self.assertRaises(ValueError):
            fresh_issues(empty_store(), self.NOW, max_rows=0)

    def test_closed_excluded_unless_requested(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/20",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                state="closed",
            )
        )
        self.assertEqual(fresh_issues(store, self.NOW)["fresh_count"], 0)
        self.assertEqual(fresh_issues(store, self.NOW, include_closed=True)["fresh_count"], 1)

    def test_assignee_count_handles_both_shapes(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/30",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                assignees=["alice", "bob"],
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/31",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                assignee="carol",
            ),
        )
        by_url = {r["url"]: r for r in fresh_issues(store, self.NOW)["fresh"]}
        self.assertEqual(by_url["https://github.com/acme/repo/issues/30"]["assignee_count"], 2)
        self.assertEqual(by_url["https://github.com/acme/repo/issues/31"]["assignee_count"], 1)
        self.assertEqual(
            by_url["https://github.com/acme/repo/issues/30"]["go_blockers"],
            ["assigned", "attempts_unknown"],
        )

    def test_solver_status_blocks_assigned_over_attempted_and_out_of_range_rows(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/40",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=4,
                assignee="alice",
                amount=400.0,
            )
        )
        row = fresh_issues(store, self.NOW)["fresh"][0]
        self.assertEqual(row["solver_status"], "no_go")
        self.assertEqual(
            row["go_blockers"],
            ["assigned", "too_many_attempts", "amount_out_of_range"],
        )

    def test_solver_status_requires_review_when_attempts_or_amount_are_unknown(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/41",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                amount=None,
                currency=None,
            )
        )
        row = fresh_issues(store, self.NOW)["fresh"][0]
        self.assertEqual(row["solver_status"], "needs_review")
        self.assertEqual(row["go_blockers"], ["attempts_unknown", "amount_unknown"])

    def test_solver_status_filter_keeps_only_matching_fresh_rows(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/50",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=1,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/51",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=6,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/52",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                amount=None,
                currency=None,
            ),
        )

        payload = fresh_issues(store, self.NOW, solver_status="go_candidate")

        self.assertEqual(payload["solver_status"], "go_candidate")
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["url"], "https://github.com/acme/repo/issues/50")

    def test_usd_range_filter_keeps_only_amounts_in_range(self) -> None:
        store = self._store(
            _store_entry(
                url="https://github.com/acme/repo/issues/53",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=1,
                amount=25.0,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/54",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=1,
                amount=301.0,
            ),
            _store_entry(
                url="https://github.com/acme/repo/issues/55",
                repository="acme/repo",
                first_seen="2026-06-11T06:00:00Z",
                attempt_count=1,
                amount=150.0,
                currency="EUR",
            ),
        )

        payload = fresh_issues(store, self.NOW, min_usd=25, max_usd=300)

        self.assertEqual(payload["min_usd"], 25)
        self.assertEqual(payload["max_usd"], 300)
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["url"], "https://github.com/acme/repo/issues/53")

    def test_invalid_usd_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            fresh_issues(empty_store(), self.NOW, min_usd=301, max_usd=300)

    def test_invalid_solver_status_filter_raises(self) -> None:
        with self.assertRaises(ValueError):
            fresh_issues(empty_store(), self.NOW, solver_status="maybe")

    def test_invalid_sort_raises(self) -> None:
        with self.assertRaises(ValueError):
            fresh_issues(empty_store(), self.NOW, sort_by="maybe")

    def test_invalid_now_raises(self) -> None:
        with self.assertRaises(ValueError):
            fresh_issues(empty_store(), "not-a-timestamp")


class FundedIssuesFreshCliTests(unittest.TestCase):
    def test_fresh_cli_json_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                attempt_count=1,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], FRESH_SCHEMA_VERSION)
            self.assertEqual(payload["fresh_count"], 1)
            self.assertIsNone(payload["solver_status"])
            self.assertIsNone(payload["min_usd"])
            self.assertIsNone(payload["max_usd"])
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["fresh"][0]["solver_status"], "go_candidate")

            text = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                ]
            )
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("fresh radar", text.stdout)
            self.assertIn("solver: go_candidate", text.stdout)

    def test_fresh_cli_markdown_is_actionable_for_solver_triage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                amount=150.0,
                attempt_count=1,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T07:00:00Z",
                amount=150.0,
                attempt_count=7,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--sort",
                    "solver",
                    "--format",
                    "markdown",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# PatchRail Funded Issues Fresh Radar", proc.stdout)
        self.assertIn("| Issue | USD | Age | Owner | Solver status |", proc.stdout)
        self.assertIn("[acme/repo#1](https://github.com/acme/repo/issues/1)", proc.stdout)
        self.assertIn("$150", proc.stdout)
        self.assertIn("6.0h via created_at", proc.stdout)
        self.assertIn("| acme | `go_candidate` | priority: clean solver candidate |", proc.stdout)
        self.assertIn(
            "| acme | `no_go` | discard: too_many_attempts |",
            proc.stdout,
        )

    def test_fresh_cli_go_list_only_prints_clean_solver_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                amount=150.0,
                attempt_count=1,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T07:00:00Z",
                amount=150.0,
                attempt_count=7,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--sort",
                    "solver",
                    "--format",
                    "go-list",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PatchRail funded-issues GO candidates", proc.stdout)
        self.assertIn("Fresh: 2  GO: 1", proc.stdout)
        self.assertIn("acme/repo#1 | $150 | 6.0h via created_at", proc.stdout)
        self.assertIn("https://github.com/acme/repo/issues/1", proc.stdout)
        self.assertNotIn("issues/2", proc.stdout)

    def test_fresh_cli_claim_checklist_is_ready_for_pr_claim_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                amount=150.0,
                attempt_count=1,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T07:00:00Z",
                amount=150.0,
                attempt_count=7,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--sort",
                    "solver",
                    "--format",
                    "claim-checklist",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PatchRail funded-issues claim checklist", proc.stdout)
        self.assertIn("Fresh: 2  GO: 1", proc.stdout)
        self.assertIn("1. acme/repo#1 - $150", proc.stdout)
        self.assertIn("Re-open issue and confirm no assignee", proc.stdout)
        self.assertIn("Add `/claim #1` in the PR only after the PR is ready.", proc.stdout)
        self.assertNotIn("issues/2", proc.stdout)

    def test_fresh_cli_can_filter_by_solver_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                attempt_count=1,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                attempt_count=8,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--solver-status",
                    "go_candidate",
                    "--sort",
                    "solver",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["solver_status"], "go_candidate")
        self.assertEqual(payload["sort"], "solver")
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["url"], "https://github.com/acme/repo/issues/1")

    def test_fresh_cli_can_filter_by_usd_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T06:00:00Z",
                amount=50.0,
                attempt_count=1,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T05:00:00Z",
                amount=500.0,
                attempt_count=1,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--min-usd",
                    "25",
                    "--max-usd",
                    "300",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["min_usd"], 25.0)
        self.assertEqual(payload["max_usd"], 300.0)
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["url"], "https://github.com/acme/repo/issues/1")

    def test_fresh_cli_can_limit_rows_after_sort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = empty_store()
            store["entries"]["https://github.com/acme/repo/issues/1"] = _store_entry(
                url="https://github.com/acme/repo/issues/1",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T10:00:00Z",
                attempt_count=8,
            )
            store["entries"]["https://github.com/acme/repo/issues/2"] = _store_entry(
                url="https://github.com/acme/repo/issues/2",
                repository="acme/repo",
                first_seen="2026-06-11T00:00:00Z",
                created_at="2026-06-11T08:00:00Z",
                attempt_count=1,
            )
            save_store(store_path, store)

            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--now",
                    "2026-06-11T12:00:00Z",
                    "--sort",
                    "solver",
                    "--max-rows",
                    "1",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["limit"], 1)
        self.assertEqual(payload["fresh_count_before_limit"], 2)
        self.assertEqual(payload["fresh_count"], 1)
        self.assertEqual(payload["fresh"][0]["url"], "https://github.com/acme/repo/issues/2")

    def test_fresh_cli_rejects_zero_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            save_store(store_path, empty_store())
            proc = run_patchrail(
                [
                    "funded-issues",
                    "fresh",
                    "--store",
                    str(store_path),
                    "--max-rows",
                    "0",
                ]
            )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("max_rows must be at least 1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
