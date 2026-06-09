from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from patchrail.funded_issues.discovery import FundedIssue
from patchrail.funded_issues.source_noise import (
    apply_source_noise_to_store,
    assess_owner_source_noise,
    entries_by_owner,
)
from patchrail.funded_issues.store import (
    apply_recheck_to_store,
    empty_store,
    load_store,
    merge_into_store,
    save_store,
    store_status,
)
from patchrail.web_metrics import build_payloads, default_funded_source

NOW = "2026-06-10T12:00:00Z"

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


# --- owner fixtures -------------------------------------------------------

# A throwaway trap org: brand-new, single repo, no website, no verifiable
# payout, spamming near-identical honeypot bounties.
TRAP_OWNER = "securebananalabs"
TRAP_META = {
    "account_age_days": 26,
    "public_repos": 1,
    "followers": 2,
    "has_website": False,
    "payout_verifiable": False,
}

# An automated aggregator: an old, well-followed account, but no website, no
# verifiable payout, and a wall of templated digest issues.
AGGREGATOR_OWNER = "relayhop"
AGGREGATOR_META = {
    "account_age_days": 1200,
    "public_repos": 18,
    "followers": 240,
    "has_website": False,
    "payout_verifiable": False,
}

# A legitimate sponsor: an established org with a website and verifiable
# payouts, posting a handful of distinct issues.
LEGIT_OWNER = "tenstorrent"
LEGIT_META = {
    "account_age_days": 2200,
    "public_repos": 140,
    "followers": 5100,
    "has_website": True,
    "payout_verifiable": True,
}


def _entry(owner: str, title: str, url: str, state: str = "active") -> dict:
    return {
        "issue": {"repository": f"{owner}/repo", "title": title, "url": url},
        "state": state,
        "noise_flags": [],
    }


def _trap_entries() -> list[dict]:
    return [
        _entry(
            TRAP_OWNER,
            "Urgent Solidity bounty fix reentrancy guard now",
            f"https://github.com/{TRAP_OWNER}/repo/issues/{i}",
        )
        for i in range(6)
    ]


def _aggregator_entries() -> list[dict]:
    return [
        _entry(
            AGGREGATOR_OWNER,
            "Radar aggregated funded issue digest weekly report",
            f"https://github.com/{AGGREGATOR_OWNER}/repo/issues/{i}",
        )
        for i in range(5)
    ]


def _legit_entries() -> list[dict]:
    titles = [
        "Fix flaky integration test in nix packaging",
        "Improve docs for tensor scheduling api",
        "Add benchmark harness for matmul kernels",
    ]
    return [
        _entry(
            LEGIT_OWNER,
            title,
            f"https://github.com/{LEGIT_OWNER}/repo/issues/{i}",
        )
        for i, title in enumerate(titles)
    ]


class OwnerSourceNoiseHeuristicTests(unittest.TestCase):
    def test_trap_org_is_flagged_with_full_flag_set(self) -> None:
        result = assess_owner_source_noise(TRAP_META, _trap_entries(), now=NOW)
        self.assertTrue(result["source_noise"])
        self.assertEqual(
            result["noise_flags"],
            [
                "anomalous_volume",
                "few_followers",
                "low_repos",
                "new_account",
                "no_website",
                "unverifiable_payout",
            ],
        )
        # Four strong flags drive the verdict; the two supporting flags do not.
        self.assertEqual(
            result["strong_flags"],
            ["anomalous_volume", "new_account", "no_website", "unverifiable_payout"],
        )
        self.assertEqual(result["strong_flag_count"], 4)
        self.assertEqual(result["tracked_entries"], 6)

    def test_aggregator_is_flagged_despite_old_popular_account(self) -> None:
        result = assess_owner_source_noise(AGGREGATOR_META, _aggregator_entries(), now=NOW)
        self.assertTrue(result["source_noise"])
        # No age/repo/follower flags: it is condemned purely on website,
        # payout verifiability, and templated volume.
        self.assertEqual(
            result["noise_flags"],
            ["anomalous_volume", "no_website", "unverifiable_payout"],
        )
        self.assertEqual(result["strong_flag_count"], 3)

    def test_legit_sponsor_is_clean(self) -> None:
        result = assess_owner_source_noise(LEGIT_META, _legit_entries(), now=NOW)
        self.assertFalse(result["source_noise"])
        self.assertEqual(result["noise_flags"], [])
        self.assertEqual(result["strong_flag_count"], 0)

    def test_volume_below_threshold_is_not_anomalous(self) -> None:
        # Same templated title, but only three entries: not enough volume.
        few = _trap_entries()[:3]
        result = assess_owner_source_noise(
            {"has_website": True, "payout_verifiable": True, "public_repos": 50, "followers": 99},
            few,
            now=NOW,
        )
        self.assertNotIn("anomalous_volume", result["noise_flags"])
        self.assertFalse(result["source_noise"])

    def test_two_strong_flags_is_the_threshold(self) -> None:
        # No website + unverifiable payout = exactly two strong flags -> flagged,
        # even with a clean age/repo/follower profile and distinct titles.
        result = assess_owner_source_noise(
            {
                "account_age_days": 2000,
                "public_repos": 30,
                "followers": 500,
                "has_website": False,
                "payout_verifiable": False,
            },
            _legit_entries(),
            now=NOW,
        )
        self.assertEqual(result["strong_flag_count"], 2)
        self.assertTrue(result["source_noise"])


def _store_issue(owner: str, title: str, url: str, state: str = "active") -> FundedIssue:
    return FundedIssue(
        id=url.rsplit("/", 1)[-1],
        platform="github",
        repository=f"{owner}/repo",
        issue_number=int(url.rsplit("/", 1)[-1]),
        title=title,
        url=url,
        opportunity_state=state,
    )


def _mixed_store() -> dict:
    """A store with a flagged trap org, a flagged aggregator, and a clean sponsor."""

    store = empty_store()
    issues: list[FundedIssue] = []
    for i in range(6):
        issues.append(
            _store_issue(
                TRAP_OWNER,
                "Urgent Solidity bounty fix reentrancy guard now",
                f"https://github.com/{TRAP_OWNER}/repo/issues/{i}",
            )
        )
    for i in range(5):
        issues.append(
            _store_issue(
                AGGREGATOR_OWNER,
                "Radar aggregated funded issue digest weekly report",
                f"https://github.com/{AGGREGATOR_OWNER}/repo/issues/{i}",
            )
        )
    for i, title in enumerate(
        [
            "Fix flaky integration test in nix packaging",
            "Improve docs for tensor scheduling api",
            "Add benchmark harness for matmul kernels",
        ]
    ):
        issues.append(
            _store_issue(LEGIT_OWNER, title, f"https://github.com/{LEGIT_OWNER}/repo/issues/{i}")
        )
    merge_into_store(store, issues, NOW)
    apply_source_noise_to_store(
        store,
        {TRAP_OWNER: TRAP_META, AGGREGATOR_OWNER: AGGREGATOR_META, LEGIT_OWNER: LEGIT_META},
        now=NOW,
    )
    return store


class SourceNoisePersistenceTests(unittest.TestCase):
    def test_apply_stamps_owner_verdict_onto_entries(self) -> None:
        store = _mixed_store()
        flagged = {
            url: entry["noise_flags"]
            for url, entry in store["entries"].items()
            if entry["noise_flags"]
        }
        # 6 trap + 5 aggregator entries flagged; 3 legit entries stay clean.
        self.assertEqual(len(flagged), 11)
        trap_url = f"https://github.com/{TRAP_OWNER}/repo/issues/0"
        self.assertIn("anomalous_volume", store["entries"][trap_url]["noise_flags"])
        legit_url = f"https://github.com/{LEGIT_OWNER}/repo/issues/0"
        self.assertEqual(store["entries"][legit_url]["noise_flags"], [])

    def test_noise_flags_survive_remerge(self) -> None:
        store = _mixed_store()
        trap_url = f"https://github.com/{TRAP_OWNER}/repo/issues/0"
        before = list(store["entries"][trap_url]["noise_flags"])
        # Re-merge the same issues at a later timestamp: an upsert must not wipe
        # the owner verdict.
        merge_into_store(
            store,
            [
                _store_issue(
                    TRAP_OWNER,
                    "Urgent Solidity bounty fix reentrancy guard now",
                    trap_url,
                )
            ],
            "2026-06-11T00:00:00Z",
        )
        self.assertEqual(store["entries"][trap_url]["noise_flags"], before)

    def test_noise_flags_survive_apply_recheck(self) -> None:
        store = _mixed_store()
        trap_url = f"https://github.com/{TRAP_OWNER}/repo/issues/0"
        before = list(store["entries"][trap_url]["noise_flags"])
        apply_recheck_to_store(
            store,
            [{"url": trap_url, "state": "closed"}],
            "2026-06-12T00:00:00Z",
        )
        entry = store["entries"][trap_url]
        self.assertEqual(entry["state"], "closed")
        self.assertEqual(entry["noise_flags"], before)

    def test_noise_flags_survive_save_load_round_trip(self) -> None:
        store = _mixed_store()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            save_store(path, store)
            reloaded = load_store(path)
        trap_url = f"https://github.com/{TRAP_OWNER}/repo/issues/0"
        self.assertEqual(
            reloaded["entries"][trap_url]["noise_flags"],
            store["entries"][trap_url]["noise_flags"],
        )


class StoreStatusBreakdownTests(unittest.TestCase):
    def test_status_reports_tracked_noise_and_clean_active(self) -> None:
        status = store_status(_mixed_store(), NOW)
        self.assertEqual(status["tracked_total"], 14)
        self.assertEqual(status["total_entries"], 14)
        self.assertEqual(status["noise_flagged"], 11)
        # Only the 3 clean legit entries count as clean-active.
        self.assertEqual(status["clean_active"], 3)


class TrackStatusCliBreakdownTests(unittest.TestCase):
    def test_track_status_json_and_text_expose_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            save_store(store_path, _mixed_store())

            proc_json = run_patchrail(
                ["funded-issues", "track-status", "--store", str(store_path), "--format", "json"]
            )
            self.assertEqual(proc_json.returncode, 0, proc_json.stderr)
            payload = json.loads(proc_json.stdout)
            self.assertEqual(payload["tracked_total"], 14)
            self.assertEqual(payload["noise_flagged"], 11)
            self.assertEqual(payload["clean_active"], 3)

            proc_text = run_patchrail(
                ["funded-issues", "track-status", "--store", str(store_path), "--format", "text"]
            )
            self.assertEqual(proc_text.returncode, 0, proc_text.stderr)
            self.assertIn("Source-noise breakdown:", proc_text.stdout)
            self.assertIn("noise flagged: 11", proc_text.stdout)
            self.assertIn("clean active: 3", proc_text.stdout)


class WebMetricsBreakdownTests(unittest.TestCase):
    def test_tracker_store_block_carries_source_noise_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            desk_dir = Path(tmp) / "desk"
            store_path = desk_dir / "tracker" / "funded-issues-store.json"
            save_store(store_path, _mixed_store())
            web_dir = Path(tmp) / "web"

            landing, _sources, product, _summary = build_payloads(
                web_dir=web_dir,
                product_repo=REPO_ROOT,
                funded_source=default_funded_source(REPO_ROOT),
                desk_dir=desk_dir,
            )

            for payload in (landing["evidence"]["tracker_store"], product["tracker_store"]):
                self.assertTrue(payload["present"])
                self.assertEqual(payload["tracked_total"], 14)
                self.assertEqual(payload["noise_flagged"], 11)
                self.assertEqual(payload["clean_active"], 3)
                # Existing keys are preserved for backward compatibility.
                self.assertEqual(payload["total_entries"], 14)
                self.assertIn("states", payload)
                self.assertIn("live_by_source", payload)


def _api_form_entry(owner: str, repo: str, number: int) -> tuple[str, dict]:
    """One entry shaped like the production tracker store.

    Production stores key entries by the GitHub API issue URL and carry the
    API-derived ``repos/<owner>`` repository form, not ``owner/repo``.
    """

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    return url, {
        "issue": {
            "repository": f"repos/{owner}",
            "title": f"[$100] task {number}",
            "url": url,
        },
        "state": "active",
        "noise_flags": [],
    }


class ProductionStoreShapeTests(unittest.TestCase):
    """Regression: a real store's repos/<owner> form must group by true owner.

    Before the fix, every production entry collapsed into one synthetic
    'repos' owner with no metadata, flagging the entire store.
    """

    def _store(self) -> dict:
        entries = dict(
            _api_form_entry(owner, repo, number)
            for owner, repo, number in (
                ("good-sponsor", "website", 1),
                ("good-sponsor", "website", 2),
                ("trap-org", "honeypot", 10),
                ("trap-org", "honeypot", 11),
            )
        )
        return {"entries": entries}

    def test_entries_group_by_true_owner(self) -> None:
        grouped = entries_by_owner(self._store())
        self.assertEqual(sorted(grouped), ["good-sponsor", "trap-org"])
        self.assertNotIn("repos", grouped)

    def test_owner_with_clean_metadata_stays_clean(self) -> None:
        store = self._store()
        summary = apply_source_noise_to_store(
            store,
            {
                "good-sponsor": {
                    "created_at": "2015-01-01T00:00:00Z",
                    "public_repos": 50,
                    "followers": 4000,
                    "has_website": True,
                    "payout_verifiable": True,
                }
            },
            now=NOW,
        )
        self.assertEqual(summary["owners_assessed"], 2)
        self.assertEqual(summary["owners_without_metadata"], ["trap-org"])
        flags_by_owner = {
            owner: [entry["noise_flags"] for entry in owner_entries]
            for owner, owner_entries in entries_by_owner(store).items()
        }
        self.assertEqual(flags_by_owner["good-sponsor"], [[], []])
        for flags in flags_by_owner["trap-org"]:
            self.assertIn("unverifiable_payout", flags)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
