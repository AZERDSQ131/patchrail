from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest

from patchrail.funded_issues.discovery import FundedIssue
from patchrail.funded_issues.store import empty_store, merge_into_store, save_store


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _store_issue(
    *,
    url: str,
    platform: str,
    state: str,
    amount: float | None = None,
    currency: str | None = None,
) -> FundedIssue:
    repository = "example/project"
    issue_number = abs(hash(url)) % 10000
    return FundedIssue(
        id=f"example-project-{issue_number}",
        platform=platform,
        repository=repository,
        issue_number=issue_number,
        title="Fix flaky integration test",
        url=url,
        funding_amount=amount,
        funding_currency=currency,
        language="python",
        opportunity_state=state,
    )


def _write_tracker_store(
    desk_dir: Path,
    issues: list[FundedIssue],
    now_iso: str,
) -> Path:
    store_path = desk_dir / "tracker" / "funded-issues-store.json"
    store = empty_store()
    merge_into_store(store, list(issues), now_iso)
    save_store(store_path, store)
    return store_path


class PatchRailWebMetricsTests(unittest.TestCase):
    def test_web_metrics_update_writes_public_api_payloads_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            api_dir = web_dir / "public" / "api"
            api_dir.mkdir(parents=True)
            (api_dir / "landing-metrics.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-05-17T00:14:00Z",
                        "values": {
                            "tracked_this_week_usd": 1,
                            "active_bounties": 1,
                            "sources_monitored": 1,
                            "new_24h": 1,
                        },
                        "loading_snapshot": {
                            "tracked_this_week_usd": 1,
                            "active_bounties": 1,
                            "sources_monitored": 1,
                            "new_24h": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (api_dir / "sources-volumes.json").write_text(
                json.dumps({"as_of": "2026-05-17T00:14:00Z", "sources": []}),
                encoding="utf-8",
            )

            desk_dir = Path(tmp) / "desk"
            research = desk_dir / "research"
            research.mkdir(parents=True)
            (research / "tenstorrent-bounty-signal.md").write_text(
                "\n".join(
                    [
                        "Fuente: GitHub API, read-only.",
                        "Resultado: 15 issues bounty abiertos.",
                        "- `[Bounty $2500] Maintenance of TT Nix packages`.",
                    ]
                ),
                encoding="utf-8",
            )

            first = run_patchrail(
                [
                    "web-metrics",
                    "update",
                    "--web-dir",
                    str(web_dir),
                    "--product-repo",
                    ".",
                    "--desk-dir",
                    str(desk_dir),
                    "--format",
                    "json",
                ]
            )
            second = run_patchrail(
                [
                    "web-metrics",
                    "update",
                    "--web-dir",
                    str(web_dir),
                    "--product-repo",
                    ".",
                    "--desk-dir",
                    str(desk_dir),
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["status"], "updated")
            self.assertEqual(json.loads(second.stdout)["status"], "unchanged")

            landing = json.loads((api_dir / "landing-metrics.json").read_text(encoding="utf-8"))
            sources = json.loads((api_dir / "sources-volumes.json").read_text(encoding="utf-8"))
            product = json.loads((api_dir / "product-metrics.json").read_text(encoding="utf-8"))

            self.assertEqual(
                landing["evidence"]["schema_version"], "patchrail.web_evidence_metrics.v1"
            )
            self.assertTrue(landing["evidence"]["read_only"])
            # No tracker store present in this desk dir: heuristic path stays intact.
            self.assertEqual(landing["evidence"]["tracker_store"], {"present": False})
            self.assertEqual(product["tracker_store"], {"present": False})
            self.assertGreaterEqual(landing["values"]["active_bounties"], 17)
            self.assertGreaterEqual(landing["values"]["tracked_this_week_usd"], 4250)
            self.assertNotIn("/Volumes/", json.dumps(landing))
            self.assertNotIn("/Users/", json.dumps(landing))
            self.assertIn({"name": "GitHub Issues", "volume": 16}, sources["sources"])
            self.assertIn({"name": "Algora", "volume": 1}, sources["sources"])
            self.assertEqual(product["schema_version"], "patchrail.product_metrics.v1")
            self.assertEqual(product["product"]["repository"], "patchrail/patchrail")
            self.assertEqual(
                product["tracker"]["active_bounties"], landing["values"]["active_bounties"]
            )
            self.assertEqual(product["readiness"]["safe_to_list"], 1)
            self.assertEqual(product["readiness"]["go_candidates"], 1)
            self.assertIn(
                "public/api/product-metrics.json", product["automation"]["static_api_files"]
            )
            self.assertNotIn("/Volumes/", json.dumps(product))
            self.assertNotIn("/Users/", json.dumps(product))

    def test_web_metrics_update_dry_run_reports_product_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            (web_dir / "public" / "api").mkdir(parents=True)

            proc = run_patchrail(
                [
                    "web-metrics",
                    "update",
                    "--web-dir",
                    str(web_dir),
                    "--product-repo",
                    ".",
                    "--dry-run",
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "would_update")
            self.assertIn("public/api/product-metrics.json", payload["would_write"])
            self.assertFalse((web_dir / "public" / "api" / "product-metrics.json").exists())


class PatchRailWebMetricsTrackerStoreTests(unittest.TestCase):
    def _run_update(self, web_dir: Path, desk_dir: Path) -> dict:
        (web_dir / "public" / "api").mkdir(parents=True)
        proc = run_patchrail(
            [
                "web-metrics",
                "update",
                "--web-dir",
                str(web_dir),
                "--product-repo",
                ".",
                "--desk-dir",
                str(desk_dir),
                "--format",
                "json",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {
            "summary": json.loads(proc.stdout),
            "landing": json.loads(
                (web_dir / "public" / "api" / "landing-metrics.json").read_text("utf-8")
            ),
            "sources": json.loads(
                (web_dir / "public" / "api" / "sources-volumes.json").read_text("utf-8")
            ),
            "product": json.loads(
                (web_dir / "public" / "api" / "product-metrics.json").read_text("utf-8")
            ),
        }

    def test_store_is_authoritative_for_active_bounties_and_sources(self) -> None:
        now_iso = (
            datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            desk_dir = Path(tmp) / "desk"
            _write_tracker_store(
                desk_dir,
                [
                    _store_issue(url="https://example.com/a", platform="algora", state="active"),
                    _store_issue(url="https://example.com/b", platform="algora", state="active"),
                    _store_issue(url="https://example.com/c", platform="github", state="open"),
                    _store_issue(url="https://example.com/d", platform="github", state="closed"),
                ],
                now_iso,
            )

            out = self._run_update(web_dir, desk_dir)
            landing, sources, product = out["landing"], out["sources"], out["product"]

            # 3 live entries (2 active algora + 1 open github); the closed one drops out.
            self.assertEqual(landing["values"]["active_bounties"], 3)
            self.assertEqual(product["tracker"]["active_bounties"], 3)
            self.assertIn({"name": "Algora", "volume": 2}, sources["sources"])
            self.assertIn({"name": "GitHub Issues", "volume": 1}, sources["sources"])
            self.assertEqual(landing["values"]["sources_monitored"], 2)
            # new_24h mirrors the store's added_24h, which counts every entry first
            # seen in the window (all 4, including the closed one).
            self.assertEqual(landing["values"]["new_24h"], 4)

            store_block = landing["evidence"]["tracker_store"]
            self.assertTrue(store_block["present"])
            self.assertEqual(store_block["total_entries"], 4)
            self.assertEqual(store_block["states"]["active"], 3)
            self.assertEqual(store_block["states"]["closed"], 1)
            self.assertEqual(store_block["added_24h"], 4)
            self.assertEqual(store_block["live_by_source"]["Algora"], 2)
            self.assertEqual(store_block["live_by_source"]["GitHub Issues"], 1)
            self.assertTrue(product["tracker_store"]["present"])

    def test_store_usd_entries_drive_tracked_this_week_usd(self) -> None:
        now_iso = (
            datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = Path(tmp) / "web"
            desk_dir = Path(tmp) / "desk"
            _write_tracker_store(
                desk_dir,
                [
                    _store_issue(
                        url="https://example.com/a",
                        platform="algora",
                        state="active",
                        amount=750.0,
                        currency="USD",
                    ),
                    _store_issue(
                        url="https://example.com/b",
                        platform="github",
                        state="active",
                        amount=1500.0,
                        currency="USD",
                    ),
                ],
                now_iso,
            )

            out = self._run_update(web_dir, desk_dir)
            landing = out["landing"]

            self.assertEqual(landing["values"]["tracked_this_week_usd"], 2250)
            store_block = landing["evidence"]["tracker_store"]
            self.assertEqual(store_block["usd_entries"], 2)
            self.assertEqual(store_block["total_usd"], 2250.0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
