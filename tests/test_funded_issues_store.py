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
) -> dict:
    """Build a raw store entry directly so freshness logic can be exercised
    without round-tripping every optional field through the importers."""
    issue: dict = {
        "url": url,
        "reference": repository + "#1",
        "repository": repository,
        "title": "Fresh bounty",
        "funding": {"amount": 150.0, "currency": "USD", "display": "$150"},
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
            self.assertTrue(payload["read_only"])

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


if __name__ == "__main__":
    unittest.main()
