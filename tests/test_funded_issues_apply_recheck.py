from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchrail.cli import _normalize_recheck_observation
from patchrail.funded_issues.discovery import FundedIssue
from patchrail.funded_issues.store import (
    STORE_SCHEMA_VERSION,
    apply_recheck_to_store,
    empty_store,
    merge_into_store,
    save_store,
)

URL = "https://github.com/example/project/issues/42"

SEEN = "2026-04-01T12:00:00Z"
NOW = "2026-06-09T12:00:00Z"


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _issue(*, url: str = URL, state: str = "active") -> FundedIssue:
    return FundedIssue(
        id="example-project-42",
        platform="polar",
        repository="example/project",
        issue_number=42,
        title="Reduce flaky integration test timeout",
        url=url,
        funding_amount=250.0,
        funding_currency="USD",
        language="python",
        opportunity_state=state,
        contribution_guidelines_url="https://example.com/CONTRIBUTING.md",
        contribution_signals=["reproduction included"],
    )


def _seeded_store(*, state: str = "active", url: str = URL, seen: str = SEEN) -> dict:
    store = empty_store()
    merge_into_store(store, [_issue(url=url, state=state)], seen)
    return store


class ApplyRecheckStateTests(unittest.TestCase):
    def test_closed_observation_transitions_to_closed(self) -> None:
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(
            store, [{"url": URL, "state": "closed", "closed_at": NOW}], NOW
        )
        self.assertEqual(summary.matched, 1)
        self.assertEqual(summary.to_closed, 1)
        entry = store["entries"][URL]
        self.assertEqual(entry["state"], "closed")
        self.assertEqual(entry["last_checked"], NOW)
        self.assertEqual(
            entry["state_history"][-1], {"state": "closed", "at": NOW, "from": "active"}
        )

    def test_open_past_threshold_transitions_to_stale(self) -> None:
        # updated_at is ~69 days before now, beyond the 45-day default.
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(
            store, [{"url": URL, "state": "open", "updated_at": "2026-04-01T12:00:00Z"}], NOW
        )
        self.assertEqual(summary.to_stale, 1)
        self.assertEqual(store["entries"][URL]["state"], "stale")

    def test_threshold_boundary_is_inclusive_active(self) -> None:
        # Exactly stale_after_days old -> NOT yet stale (strictly-greater rule).
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(
            store,
            [{"url": URL, "state": "open", "updated_at": "2026-04-25T12:00:00Z"}],
            "2026-06-09T12:00:00Z",
            stale_after_days=45,
        )
        self.assertEqual(summary.to_active, 0)
        self.assertEqual(summary.unchanged, 1)
        self.assertEqual(store["entries"][URL]["state"], "active")

    def test_threshold_one_second_over_is_stale(self) -> None:
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(
            store,
            [{"url": URL, "state": "open", "updated_at": "2026-04-25T11:59:59Z"}],
            "2026-06-09T12:00:00Z",
            stale_after_days=45,
        )
        self.assertEqual(summary.to_stale, 1)
        self.assertEqual(store["entries"][URL]["state"], "stale")

    def test_stale_revives_to_active_when_fresh(self) -> None:
        store = _seeded_store(state="stale")
        summary = apply_recheck_to_store(
            store, [{"url": URL, "state": "open", "updated_at": NOW}], NOW
        )
        self.assertEqual(summary.to_active, 1)
        entry = store["entries"][URL]
        self.assertEqual(entry["state"], "active")
        self.assertEqual(
            entry["state_history"][-1], {"state": "active", "at": NOW, "from": "stale"}
        )

    def test_unmatched_urls_are_ignored_and_counted(self) -> None:
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(
            store,
            [
                {"url": "https://github.com/ghost/repo/issues/1", "state": "closed"},
                {"state": "closed"},  # missing url
            ],
            NOW,
        )
        self.assertEqual(summary.checked, 2)
        self.assertEqual(summary.matched, 0)
        self.assertEqual(summary.unmatched, 2)
        self.assertEqual(store["entries"][URL]["state"], "active")

    def test_state_history_only_appended_on_real_transition(self) -> None:
        store = _seeded_store(state="active")
        before = len(store["entries"][URL]["state_history"])
        summary = apply_recheck_to_store(
            store, [{"url": URL, "state": "open", "updated_at": NOW}], NOW
        )
        self.assertEqual(summary.unchanged, 1)
        self.assertEqual(summary.to_active, 0)
        entry = store["entries"][URL]
        # No transition, but last_checked still advances.
        self.assertEqual(len(entry["state_history"]), before)
        self.assertEqual(entry["last_checked"], NOW)

    def test_idempotent_second_pass_yields_no_transitions(self) -> None:
        store = _seeded_store(state="active")
        first = apply_recheck_to_store(store, [{"url": URL, "state": "closed"}], NOW)
        self.assertEqual(first.to_closed, 1)
        second = apply_recheck_to_store(
            store, [{"url": URL, "state": "closed"}], "2026-06-10T12:00:00Z"
        )
        self.assertEqual(second.to_closed, 0)
        self.assertEqual(second.to_stale, 0)
        self.assertEqual(second.to_active, 0)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(len(store["entries"][URL]["state_history"]), 2)

    def test_github_api_shape_is_normalized(self) -> None:
        store = _seeded_store(state="active")
        # GitHub API issue object: html_url, state, updated_at, assignees list.
        # The CLI normalizer maps it to the native vocabulary the store consumes.
        observation = _normalize_recheck_observation(
            {
                "html_url": URL,
                "state": "closed",
                "updated_at": NOW,
                "closed_at": NOW,
                "comments": 4,
                "assignees": [{"login": "a"}, {"login": "b"}],
            }
        )
        self.assertEqual(observation["url"], URL)
        self.assertEqual(observation["assignee_count"], 2)
        summary = apply_recheck_to_store(store, [observation], NOW)
        self.assertEqual(summary.to_closed, 1)
        self.assertEqual(store["entries"][URL]["state"], "closed")

    def test_invalid_now_raises_before_mutation(self) -> None:
        store = _seeded_store(state="active")
        with self.assertRaises(ValueError):
            apply_recheck_to_store(store, [{"url": URL, "state": "closed"}], "not-a-timestamp")
        # Store untouched.
        self.assertEqual(store["entries"][URL]["state"], "active")
        self.assertEqual(store["entries"][URL]["last_checked"], SEEN)

    def test_summary_to_dict_shape(self) -> None:
        store = _seeded_store(state="active")
        summary = apply_recheck_to_store(store, [{"url": URL, "state": "closed"}], NOW)
        payload = summary.to_dict()
        self.assertEqual(payload["checked"], 1)
        self.assertEqual(payload["matched"], 1)
        self.assertEqual(payload["unmatched"], 0)
        self.assertEqual(payload["transitions"], {"to_closed": 1, "to_stale": 0, "to_active": 0})
        self.assertEqual(payload["unchanged"], 0)
        self.assertEqual(payload["transition_log"][0]["url"], URL)


class ApplyRecheckCliTests(unittest.TestCase):
    def _seed_store_file(self, path: Path, *, state: str = "active") -> None:
        save_store(path, _seeded_store(state=state))

    def test_cli_end_to_end_closes_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            input_path = Path(tmp) / "obs.json"
            self._seed_store_file(store_path)
            input_path.write_text(
                json.dumps([{"url": URL, "state": "closed", "closed_at": NOW}]), "utf-8"
            )

            proc = run_patchrail(
                [
                    "funded-issues",
                    "apply-recheck",
                    "--store",
                    str(store_path),
                    "--input",
                    str(input_path),
                    "--now",
                    NOW,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(
                payload["schema_version"], "patchrail.funded_issues.recheck_summary.v1"
            )
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["summary"]["transitions"]["to_closed"], 1)

            saved = json.loads(store_path.read_text("utf-8"))
            self.assertEqual(saved["schema_version"], STORE_SCHEMA_VERSION)
            self.assertEqual(saved["entries"][URL]["state"], "closed")

    def test_cli_dry_run_does_not_write_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            input_path = Path(tmp) / "obs.json"
            self._seed_store_file(store_path)
            before = store_path.read_text("utf-8")
            input_path.write_text(json.dumps([{"url": URL, "state": "closed"}]), "utf-8")

            proc = run_patchrail(
                [
                    "funded-issues",
                    "apply-recheck",
                    "--store",
                    str(store_path),
                    "--input",
                    str(input_path),
                    "--now",
                    NOW,
                    "--dry-run",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["transitions"]["to_closed"], 1)
            # Store file is byte-identical: nothing was written.
            self.assertEqual(store_path.read_text("utf-8"), before)

    def test_cli_accepts_observations_object_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            input_path = Path(tmp) / "obs.json"
            self._seed_store_file(store_path)
            input_path.write_text(
                json.dumps({"observations": [{"url": URL, "state": "closed"}]}), "utf-8"
            )
            proc = run_patchrail(
                [
                    "funded-issues",
                    "apply-recheck",
                    "--store",
                    str(store_path),
                    "--input",
                    str(input_path),
                    "--now",
                    NOW,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["summary"]["transitions"]["to_closed"], 1)

    def test_cli_accepts_github_api_issue_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            input_path = Path(tmp) / "obs.json"
            self._seed_store_file(store_path)
            input_path.write_text(
                json.dumps(
                    [
                        {
                            "html_url": URL,
                            "state": "closed",
                            "updated_at": NOW,
                            "closed_at": NOW,
                            "comments": 1,
                            "assignees": [{"login": "x"}],
                        }
                    ]
                ),
                "utf-8",
            )
            proc = run_patchrail(
                [
                    "funded-issues",
                    "apply-recheck",
                    "--store",
                    str(store_path),
                    "--input",
                    str(input_path),
                    "--now",
                    NOW,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["summary"]["transitions"]["to_closed"], 1)
            saved = json.loads(store_path.read_text("utf-8"))
            self.assertEqual(saved["entries"][URL]["state"], "closed")

    def test_cli_invalid_now_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            input_path = Path(tmp) / "obs.json"
            self._seed_store_file(store_path)
            input_path.write_text(json.dumps([{"url": URL, "state": "closed"}]), "utf-8")
            proc = run_patchrail(
                [
                    "funded-issues",
                    "apply-recheck",
                    "--store",
                    str(store_path),
                    "--input",
                    str(input_path),
                    "--now",
                    "nope",
                ]
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Invalid recheck input", proc.stderr)

    def test_schema_command_exposes_recheck_summary(self) -> None:
        proc = run_patchrail(["schema", "funded-issues-recheck-summary"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        schema = json.loads(proc.stdout)
        self.assertIn("https://patchrail.dev/schemas/", schema["$id"])
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "patchrail.funded_issues.recheck_summary.v1",
        )
        self.assertEqual(schema["properties"]["read_only"]["const"], True)
        self.assertIn("blocked_actions", schema["required"])
        self.assertIn("requirements", schema["required"])


if __name__ == "__main__":
    unittest.main()
