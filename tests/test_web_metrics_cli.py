from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


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


if __name__ == "__main__":
    raise SystemExit(unittest.main())
