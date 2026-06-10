from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchrail.funded_issues import (
    BLOCKLISTED_OWNERS,
    empty_store,
    is_blocklisted_owner,
    is_blocklisted_record,
    merge_into_store,
    purge_blocklisted_entries,
    save_store,
)
from patchrail.funded_issues.blocklist import record_owner

NOW = "2026-06-10T12:00:00Z"


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _record(url: str, repository: str = "unknown/unknown", **extra: object) -> dict[str, object]:
    record: dict[str, object] = {
        "url": url,
        "repository": repository,
        "title": "Example issue",
        "opportunity_state": "active",
    }
    record.update(extra)
    return record


class BlocklistedOwnerTests(unittest.TestCase):
    def test_blocklist_membership_is_case_insensitive(self) -> None:
        self.assertIn("securebananalabs", BLOCKLISTED_OWNERS)
        self.assertTrue(is_blocklisted_owner("SecureBananaLabs"))
        self.assertTrue(is_blocklisted_owner("  ClankerNation  "))
        self.assertTrue(is_blocklisted_owner("xevrion-v2"))
        self.assertFalse(is_blocklisted_owner("tscircuit"))
        self.assertFalse(is_blocklisted_owner(None))
        self.assertFalse(is_blocklisted_owner(""))

    def test_record_owner_prefers_explicit_owner(self) -> None:
        self.assertEqual(record_owner({"owner": "someone", "url": "x"}), "someone")

    def test_record_owner_from_api_url(self) -> None:
        record = _record("https://api.github.com/repos/ClankerNation/OpenAgents/issues/165")
        self.assertEqual(record_owner(record), "ClankerNation")
        self.assertTrue(is_blocklisted_record(record))

    def test_record_owner_from_html_url(self) -> None:
        record = _record("https://github.com/xevrion-v2/trap/issues/9")
        self.assertEqual(record_owner(record), "xevrion-v2")
        self.assertTrue(is_blocklisted_record(record))

    def test_record_owner_from_repository_forms(self) -> None:
        self.assertEqual(record_owner({"repository": "repos/SecureBananaLabs"}), "SecureBananaLabs")
        self.assertEqual(record_owner({"repository": "tscircuit/jlcsearch"}), "tscircuit")
        self.assertEqual(record_owner({}), "")
        self.assertFalse(is_blocklisted_record({}))


class MergeBlocksBlocklistedTests(unittest.TestCase):
    def test_merge_drops_blocklisted_records_and_counts_them(self) -> None:
        store = empty_store()
        summary = merge_into_store(
            store,
            [
                _record("https://github.com/tscircuit/jlcsearch/issues/92"),
                _record("https://github.com/SecureBananaLabs/trap/issues/1"),
                _record("https://api.github.com/repos/ClankerNation/OpenAgents/issues/165"),
            ],
            NOW,
        )
        self.assertEqual(summary.added, 1)
        self.assertEqual(summary.blocked, 2)
        self.assertEqual(summary.to_dict()["blocked"], 2)
        self.assertEqual(
            list(store["entries"]), ["https://github.com/tscircuit/jlcsearch/issues/92"]
        )

    def test_blocklisted_owner_cannot_reenter_on_remerge(self) -> None:
        store = empty_store()
        record = _record("https://github.com/xevrion-v2/trap/issues/9")
        for _ in range(2):
            summary = merge_into_store(store, [record], NOW)
            self.assertEqual(summary.blocked, 1)
            self.assertEqual(store["entries"], {})


class PurgeBlocklistedTests(unittest.TestCase):
    def _store_with_blocklisted_entry(self) -> dict[str, object]:
        store = empty_store()
        merge_into_store(store, [_record("https://github.com/tscircuit/core/issues/1")], NOW)
        # Simulate a legacy store written before the blocklist existed.
        store["entries"]["https://api.github.com/repos/SecureBananaLabs/trap/issues/2"] = {
            "issue": {
                "url": "https://api.github.com/repos/SecureBananaLabs/trap/issues/2",
                "repository": "repos/SecureBananaLabs",
                "title": "Test Bounty",
                "opportunity_state": "active",
            },
            "first_seen": NOW,
            "last_seen": NOW,
            "last_checked": NOW,
            "state": "active",
            "state_history": [{"state": "active", "at": NOW, "from": None}],
            "noise_flags": [],
        }
        return store

    def test_purge_removes_legacy_blocklisted_entries(self) -> None:
        store = self._store_with_blocklisted_entry()
        summary = purge_blocklisted_entries(store)
        self.assertEqual(summary["removed"], 1)
        self.assertEqual(summary["removed_owners"], ["securebananalabs"])
        self.assertEqual(list(store["entries"]), ["https://github.com/tscircuit/core/issues/1"])

    def test_purge_is_idempotent_and_clean_store_untouched(self) -> None:
        store = self._store_with_blocklisted_entry()
        purge_blocklisted_entries(store)
        summary = purge_blocklisted_entries(store)
        self.assertEqual(summary["removed"], 0)
        self.assertEqual(summary["removed_owners"], [])

    def test_track_cli_self_heals_legacy_store(self) -> None:
        store = self._store_with_blocklisted_entry()
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            save_store(store_path, store)
            proc = run_patchrail(
                [
                    "funded-issues",
                    "track",
                    "--store",
                    str(store_path),
                    "--input",
                    "examples/funded-issues-readonly/issues.json",
                    "--now",
                    NOW,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["purged_blocklisted"], 1)
            self.assertEqual(payload["summary"]["blocked"], 0)
            saved = json.loads(store_path.read_text("utf-8"))
            self.assertNotIn(
                "https://api.github.com/repos/SecureBananaLabs/trap/issues/2",
                saved["entries"],
            )


if __name__ == "__main__":
    unittest.main()
