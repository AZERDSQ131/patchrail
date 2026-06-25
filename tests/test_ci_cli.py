from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from patchrail.ci.classify import RULES
from patchrail.cli import (
    _FIX_GUIDE_SLUGS,
    _ci_triage_action_url,
    _ci_triage_pack_url,
    _fix_guide_url,
    main,
)


class PatchRailCITests(unittest.TestCase):
    def test_distribution_sku1_gate_reports_traffic_gap_from_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "x.json").write_text(
                json.dumps(
                    {
                        "channel": "x",
                        "status": "posted",
                        "url": "https://x.com/pablito3_3/status/1",
                        "item_id": "1",
                        "ts_posted": "2026-06-19T07:38:47Z",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "browser route unavailable",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "devto.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["devto", "show-hn", "x"],
                        "social_post_blocked_total": 2,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [],
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "Chrome route missing extension",
                                "receipt": str(posted / "show-hn.json"),
                                "path": "opportunity-desk/outbox/requests/show-hn.json",
                                "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                                "ts_blocked": "2026-06-25T07:40:05Z",
                            },
                            {
                                "channel": "devto",
                                "reason": "copywriter unavailable; no approved local copy file",
                                "receipt": str(posted / "devto.json"),
                                "path": "opportunity-desk/outbox/requests/devto.json",
                                "ts_blocked": "2026-06-24T09:34:00Z",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--stalled-after-days",
                        "1",
                        "--paid-click-cpc-usd",
                        "0.50",
                        "--ad-cap-usd",
                        "75",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "patchrail.distribution_gate.v1")
        self.assertEqual(payload["conversion_consumer"], "SKU #1 CI Triage $19")
        self.assertEqual(payload["conversion_kpi"], "visits_and_sales_before_2026-06-30")
        self.assertIn("utm_source=github_marketplace", payload["conversion_url"])
        self.assertEqual(payload["traffic_gap"], 275)
        self.assertEqual(
            payload["traffic_pressure"],
            {
                "traffic_gap": 275,
                "days_to_gate": 5,
                "required_daily_traffic": 55.0,
                "status": "traffic_gap_before_gate",
            },
        )
        self.assertEqual(
            payload["paid_traffic_plan"],
            {
                "ad_cap_usd": 75.0,
                "ad_spend_committed_usd": 0.0,
                "ad_remaining_usd": 75.0,
                "paid_click_cpc_usd": 0.5,
                "traffic_gap": 275,
                "budget_for_gap_usd": 137.5,
                "cap_click_capacity": 150,
                "cap_covers_gap": False,
                "remaining_organic_gap_after_cap": 125,
                "recommendation": "organic_distribution_required_before_or_alongside_ads",
                "preflight_required": True,
            },
        )

        self.assertEqual(
            payload["traffic_execution_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "deadline": "2026-06-30",
                "paid_click_target": 150,
                "paid_budget_usd": 75.0,
                "organic_click_target": 125,
                "daily_organic_click_target": 25.0,
                "recommended_channel": "devto",
                "measurement_event": "sku1_visits_and_sales_delta",
            },
        )
        self.assertEqual(
            payload["channel_conversion_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "channel": "devto",
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                ),
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
                "ready_to_publish": False,
                "next_action": "copywriter_required",
            },
        )
        self.assertEqual(
            payload["channel_measurement_urls"],
            [
                {
                    "channel": "devto",
                    "owner": "copywriter",
                    "source": "blocked",
                    "next_action": "copywriter_required",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                },
                {
                    "channel": "show-hn",
                    "owner": "pablo",
                    "source": "blocked",
                    "next_action": "browser_extension_setup_required",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=show-hn&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                },
            ],
        )
        self.assertEqual(
            payload["execution_checklist"],
            [
                {
                    "name": "paid_ads_preflight",
                    "required": True,
                    "owner": "worker",
                    "amount_usd": 75.0,
                    "platform": "sku1-traffic-boost",
                    "command": (
                        "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                        "--amount 75.00 --platform sku1-traffic-boost "
                        "--campaign ci-triage-sku1-gate"
                    ),
                    "halt_flag": "~/.openclaw/run/AD_SPEND_HALT.flag",
                },
                {
                    "name": "organic_distribution",
                    "required": True,
                    "owner": "copywriter",
                    "channel": "devto",
                    "target_clicks": 125,
                    "daily_target_clicks": 25.0,
                    "next_action": "copywriter_required",
                },
                {
                    "name": "measure_gate",
                    "required": True,
                    "owner": "worker",
                    "event": "sku1_visits_and_sales_delta",
                    "command": (
                        "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                        "~/.openclaw/run/patchrail_supervisor_last.json"
                    ),
                },
            ],
        )
        self.assertEqual(
            payload["publish_post_commands"],
            {
                "channel": "devto",
                "health_command": "python3 opportunity-desk/scripts/publish_post.py health --json",
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel devto --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel devto --reason <concrete_blocker>"
                ),
            },
        )
        self.assertEqual(
            payload["channel_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "deadline": "2026-06-30",
                "channel": "devto",
                "owner": "copywriter",
                "source": "blocked",
                "next_action": "copywriter_required",
                "safe_next_step": (
                    "copywriter must create approved copy_file; "
                    "worker must not draft external prose"
                ),
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                ),
                "ready_to_publish": False,
                "copywriter_required": True,
                "copy_file": "",
                "organic_click_target": 125,
                "daily_organic_click_target": 25.0,
                "measurement_event": "sku1_visits_and_sales_delta",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel devto --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel devto --reason <concrete_blocker>"
                ),
                "copy_brief_request": {
                    "write_path": (
                        "opportunity-desk/outbox/requests/<timestamp>-sku1-devto-social-post.json"
                    ),
                    "schema": "copy_brief.social_post.v1",
                    "prohibited_fields": ["body", "draft", "email_body"],
                    "payload": {
                        "type": "social_post",
                        "channel": "devto",
                        "lead": "SKU #1 CI Triage $19",
                        "goal": (
                            "Create approved PatchRail social copy for devto that drives "
                            "measured visits to SKU #1 before 2026-06-30."
                        ),
                        "key_facts": [
                            "Product: SKU #1 CI Triage $19.",
                            "KPI: visits_and_sales_before_2026-06-30.",
                            (
                                "Channel URL with UTM: "
                                "https://patchrail.gumroad.com/l/ci-failure-triage"
                                "?utm_source=devto&utm_campaign=sku1-organic-distribution."
                            ),
                            "Organic click target: 125.",
                            "Daily organic target: 25.0.",
                            "Source: blocked.",
                            "Reason: copywriter unavailable; no approved local copy file.",
                        ],
                        "tone": "Concise, practical, maintainer-safe, no hype.",
                        "constraints": [
                            (
                                "Copywriter authors final external prose; worker does not draft "
                                "publishable text."
                            ),
                            "Brand-only: PatchRail.",
                            (
                                "No internal model/tool names, no payout or sales guarantees, "
                                "no calls or Calendly."
                            ),
                            "Use the provided UTM URL exactly for measurement.",
                        ],
                        "urgency": "normal",
                        "thread_ref": (
                            "distribution sku1-gate channel=devto; "
                            "kpi=visits_and_sales_before_2026-06-30; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                        ),
                    },
                },
            },
        )
        self.assertEqual(
            payload["copywriter_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "pending_count": 1,
                "next_channel": "devto",
                "next_brief": "opportunity-desk/outbox/requests/devto.json",
                "pending": [
                    {
                        "channel": "devto",
                        "brief": "opportunity-desk/outbox/requests/devto.json",
                        "blocked_days": 1,
                        "reason": "copywriter unavailable; no approved local copy file",
                        "next_action": "copywriter_required",
                        "safe_next_step": (
                            "copywriter must create approved copy_file; "
                            "worker must not draft external prose"
                        ),
                        "claim_after_copy_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel devto --copy-file <copywriter-approved-copy-file>"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(
            payload["browser_extension_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "owner": "pablo",
                "pending_count": 1,
                "next_channel": "show-hn",
                "next_verify_command": (
                    "python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json"
                ),
                "next_claim_after_setup_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim --channel show-hn "
                    "--copy-file products/gumroad/distribution/posts/show-hn.md"
                ),
                "next_verify_after_claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json"
                ),
                "checklist": [
                    "Open chrome://extensions in the selected logged-in Chrome profile.",
                    "Enable or install the Codex Chrome Extension for that profile.",
                    "Do not bypass login, 2FA, CAPTCHA, profile, or account controls.",
                    (
                        "After setup, run the claim-after-setup command for the channel if "
                        "copy_file exists, then rerun the verify-after-claim command."
                    ),
                ],
                "pending": [
                    {
                        "channel": "show-hn",
                        "owner": "pablo",
                        "blocked_days": 0,
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "safe_next_step": (
                            "enable/install the Codex Chrome Extension in the selected "
                            "logged-in Chrome profile for show-hn; worker must not bypass "
                            "profile/login controls"
                        ),
                        "verify_command": (
                            "python3 opportunity-desk/scripts/publish_post.py blockers "
                            "--owner pablo --json"
                        ),
                        "claim_after_setup_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel show-hn --copy-file "
                            "products/gumroad/distribution/posts/show-hn.md"
                        ),
                        "verify_after_claim_command": (
                            "python3 opportunity-desk/scripts/publish_post.py blockers "
                            "--owner pablo --json"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(payload["posted_channels"], ["x"])
        self.assertEqual(payload["blocked_channels"], ["devto", "show-hn"])
        self.assertEqual(payload["publish_health"]["blocked_total"], 2)
        self.assertEqual(payload["publish_health"]["blocked"][0]["channel"], "show-hn")
        self.assertEqual(payload["publish_health"]["uncovered_channels"], [])
        self.assertEqual(payload["blocker_owner_counts"], {"copywriter": 1, "pablo": 1})
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["next_action"])
                for item in payload["blocker_plan"]
            ],
            [
                ("devto", "copywriter", "copywriter_required"),
                ("show-hn", "pablo", "browser_extension_setup_required"),
            ],
        )
        self.assertIn(
            "worker must not draft external prose", payload["blocker_plan"][0]["safe_next_step"]
        )
        self.assertIn("worker must not bypass", payload["blocker_plan"][1]["safe_next_step"])
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["next_action"])
                for item in payload["blocker_queue"]
            ],
            [
                ("devto", "copywriter", "copywriter_required"),
                ("show-hn", "pablo", "browser_extension_setup_required"),
            ],
        )
        self.assertEqual(payload["blocker_queue"][0]["blocked_at"], "2026-06-24T09:34:00Z")
        self.assertEqual(payload["blocker_queue"][0]["blocked_days"], 1)
        self.assertEqual(payload["blocker_queue"][1]["blocked_days"], 0)
        self.assertEqual(payload["oldest_blocked_days"], 1)
        self.assertEqual(payload["oldest_blocker"]["channel"], "devto")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "devto",
                "source": "blocked",
                "owner": "copywriter",
                "next_action": "copywriter_required",
                "safe_next_step": "copywriter must create approved copy_file; worker must not draft external prose",
                "reason": "copywriter unavailable; no approved local copy file",
                "blocked_at": "2026-06-24T09:34:00Z",
                "blocked_days": 1,
            },
        )
        self.assertEqual(
            payload["owner_next_actions"],
            [
                {
                    "owner": "copywriter",
                    "channel": "devto",
                    "pending_channels": ["devto"],
                    "pending_count": 1,
                    "next_action": "copywriter_required",
                    "safe_next_step": "copywriter must create approved copy_file; worker must not draft external prose",
                    "source": "blocked",
                    "oldest_blocked_days": 1,
                },
                {
                    "owner": "pablo",
                    "channel": "show-hn",
                    "pending_channels": ["show-hn"],
                    "pending_count": 1,
                    "next_action": "browser_extension_setup_required",
                    "safe_next_step": "enable/install the Codex Chrome Extension in the selected logged-in Chrome profile for show-hn; worker must not bypass profile/login controls",
                    "source": "blocked",
                    "oldest_blocked_days": 0,
                },
            ],
        )
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")
        self.assertEqual(payload["channel_closeout_plan"]["required"], False)
        self.assertEqual(payload["channel_closeout_plan"]["all_channels_covered"], False)
        self.assertEqual(payload["channel_closeout_plan"]["next_action"], "copywriter_required")
        self.assertEqual(
            payload["channel_closeout_plan"]["safe_next_step"],
            "copywriter must create approved copy_file; worker must not draft external prose",
        )
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertEqual(payload["stalled_after_days"], 1)
        self.assertEqual(payload["stalled_owner_counts"], {"copywriter": 1})
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["blocked_days"])
                for item in payload["stalled_blockers"]
            ],
            [("devto", "copywriter", 1)],
        )
        self.assertEqual(
            payload["stalled_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "pending_count": 1,
                "next_owner": "copywriter",
                "next_channel": "devto",
                "next_blocked_days": 1,
                "next_brief": "opportunity-desk/outbox/requests/devto.json",
                "next_unblock_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "pending": [
                    {
                        "channel": "devto",
                        "owner": "copywriter",
                        "blocked_days": 1,
                        "brief": "opportunity-desk/outbox/requests/devto.json",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "safe_next_step": (
                            "copywriter must create approved copy_file; "
                            "worker must not draft external prose"
                        ),
                        "unblock_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel devto --copy-file <copywriter-approved-copy-file>"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(payload["stalled_handoff_owner"], "copywriter")

    def test_distribution_sku1_gate_recommends_uncovered_channel_when_no_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 2,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "linkedin"}, "devto"],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                    ]
                )

        self.assertEqual(exit_code, 0)
        text = stdout.getvalue()
        self.assertIn("Recommended channel: devto (claim_uncovered_distribution_channel)", text)
        self.assertIn(
            "Publish commands: health=python3 opportunity-desk/scripts/publish_post.py health --json; "
            "claim=python3 opportunity-desk/scripts/publish_post.py claim --channel devto "
            "--copy-file <copywriter-approved-copy-file>; "
            "record=python3 opportunity-desk/scripts/publish_post.py record --channel devto "
            "--url <submission_url>",
            text,
        )
        self.assertIn(
            "Traffic pressure: traffic_gap_before_gate, days_to_gate=5, "
            "required_daily_traffic=55.0",
            text,
        )
        self.assertIn(
            "Traffic execution: paid_clicks=100, paid_budget=$75.00, "
            "organic_clicks=175, daily_organic=35.0, channel=devto",
            text,
        )
        self.assertIn(
            "Channel conversion: devto "
            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=devto&utm_campaign=sku1-organic-distribution ready=True",
            text,
        )
        self.assertIn(
            "Channel measurement URLs: "
            "devto=https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=devto&utm_campaign=sku1-organic-distribution",
            text,
        )
        self.assertIn(
            "Execution checklist: paid_ads_preflight=worker, organic_distribution=worker, "
            "measure_gate=worker",
            text,
        )
        self.assertIn(
            "Owner next actions: worker=devto/claim_uncovered_distribution_channel (1 channel)",
            text,
        )
        self.assertIn("Copywriter handoff: none", text)
        self.assertIn("Stalled blockers: none", text)
        self.assertIn("Stalled handoff: none", text)
        self.assertIn("Next action: claim_uncovered_distribution_channel", text)

    def test_distribution_sku1_gate_subtracts_committed_ad_spend_from_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["reddit-sideproject", "x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-committed-usd",
                        "50",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["paid_traffic_plan"]["ad_cap_usd"], 75.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 50.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 25.0)
        self.assertEqual(payload["paid_traffic_plan"]["cap_click_capacity"], 33)
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 33)
        self.assertEqual(payload["traffic_execution_plan"]["paid_budget_usd"], 24.75)
        self.assertIn("--amount 24.75", payload["execution_checklist"][0]["command"])

    def test_distribution_sku1_gate_reads_committed_ad_spend_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["reddit-sideproject", "x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )
            ledger = Path(tmpdir) / "ledger.jsonl"
            ledger.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "charge",
                                "amount_usd": "12.34",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "refused",
                                "kind": "charge",
                                "amount_usd": "99.00",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "preauth",
                                "amount_usd": "5.00",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "refund",
                                "amount_usd": "2.00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-committed-usd",
                        "50",
                        "--ad-spend-ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["ad_spend_source"],
            {
                "source": "ledger",
                "ledger_path": str(ledger),
                "committed_usd": 15.34,
                "line_count": 4,
                "committed_lines": 3,
                "ignored_lines": 1,
            },
        )
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 15.34)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 59.66)
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 79)
        self.assertEqual(payload["traffic_execution_plan"]["paid_budget_usd"], 59.25)
        self.assertIn("--amount 59.25", payload["execution_checklist"][0]["command"])

    def test_distribution_sku1_gate_reads_committed_ad_spend_from_guard_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            ledger = Path(tmpdir) / "patchrail_ad_spend.json"
            ledger.write_text(
                json.dumps(
                    {
                        "ad_cap_usd": 75.0,
                        "ad_charges": 0,
                        "ad_spend_committed_usd": 12.5,
                        "ad_spend_remaining_usd": 62.5,
                        "by_platform": {},
                        "halted": False,
                        "source": "ad_spend_guard",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["ad_spend_source"],
            {
                "source": "ad_spend_guard",
                "ledger_path": str(ledger),
                "committed_usd": 12.5,
                "line_count": 1,
                "committed_lines": 1,
                "ignored_lines": 0,
                "snapshot_format": "json_object",
            },
        )
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 12.5)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 62.5)
        self.assertEqual(payload["measurement_packet"]["ad_remaining_usd"], 62.5)

    def test_distribution_sku1_gate_unblocks_blocked_receipts_without_health_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "devto.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")
        self.assertEqual(payload["blocker_queue"][0]["channel"], "devto")

    def test_distribution_sku1_gate_uses_health_to_clear_historical_blocked_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "devto-old-block.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file for channel",
                        "ts_blocked": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["devto"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(payload["blocked_channels"], [])
        self.assertEqual(payload["blocker_plan"], [])
        self.assertEqual(payload["blocker_queue"], [])
        self.assertEqual(payload["receipt_status_counts"], {"blocked": 1})
        self.assertEqual(payload["publish_health"]["blocked_total"], 0)

    def test_distribution_sku1_gate_recommends_linkedin_expansion_after_base_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "ship_more_distribution")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "linkedin",
                "source": "expansion",
                "owner": "worker",
                "next_action": "create_social_post_brief",
                "safe_next_step": (
                    "create facts-only social_post brief for linkedin; "
                    "copywriter authors external prose before claim/publish"
                ),
                "reason": "traffic_gap_remaining_after_base_channels_covered",
            },
        )
        self.assertEqual(payload["traffic_execution_plan"]["recommended_channel"], "linkedin")
        self.assertEqual(payload["channel_conversion_plan"]["channel"], "linkedin")
        self.assertEqual(
            payload["channel_conversion_plan"]["url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution",
        )
        self.assertEqual(
            payload["channel_measurement_urls"],
            [
                {
                    "channel": "linkedin",
                    "owner": "worker",
                    "source": "expansion",
                    "next_action": "create_social_post_brief",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                }
            ],
        )
        self.assertEqual(
            payload["channel_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "deadline": "2026-06-30",
                "channel": "linkedin",
                "owner": "worker",
                "source": "expansion",
                "next_action": "create_social_post_brief",
                "safe_next_step": (
                    "create facts-only social_post brief for linkedin; "
                    "copywriter authors external prose before claim/publish"
                ),
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                ),
                "ready_to_publish": False,
                "copywriter_required": True,
                "copy_file": "",
                "organic_click_target": 172,
                "daily_organic_click_target": 34.4,
                "measurement_event": "sku1_visits_and_sales_delta",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel linkedin --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel linkedin --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel linkedin --reason <concrete_blocker>"
                ),
                "copy_brief_request": {
                    "write_path": (
                        "opportunity-desk/outbox/requests/"
                        "<timestamp>-sku1-linkedin-social-post.json"
                    ),
                    "schema": "copy_brief.social_post.v1",
                    "prohibited_fields": ["body", "draft", "email_body"],
                    "payload": {
                        "type": "social_post",
                        "channel": "linkedin",
                        "lead": "SKU #1 CI Triage $19",
                        "goal": (
                            "Create approved PatchRail social copy for linkedin that drives "
                            "measured visits to SKU #1 before 2026-06-30."
                        ),
                        "key_facts": [
                            "Product: SKU #1 CI Triage $19.",
                            "KPI: visits_and_sales_before_2026-06-30.",
                            (
                                "Channel URL with UTM: "
                                "https://patchrail.gumroad.com/l/ci-failure-triage"
                                "?utm_source=linkedin&utm_campaign=sku1-organic-distribution."
                            ),
                            "Organic click target: 172.",
                            "Daily organic target: 34.4.",
                            "Source: expansion.",
                            "Reason: traffic_gap_remaining_after_base_channels_covered.",
                        ],
                        "tone": "Concise, practical, maintainer-safe, no hype.",
                        "constraints": [
                            (
                                "Copywriter authors final external prose; worker does not draft "
                                "publishable text."
                            ),
                            "Brand-only: PatchRail.",
                            (
                                "No internal model/tool names, no payout or sales guarantees, "
                                "no calls or Calendly."
                            ),
                            "Use the provided UTM URL exactly for measurement.",
                        ],
                        "urgency": "normal",
                        "thread_ref": (
                            "distribution sku1-gate channel=linkedin; "
                            "kpi=visits_and_sales_before_2026-06-30; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                        ),
                    },
                },
            },
        )
        self.assertFalse(payload["channel_conversion_plan"]["ready_to_publish"])
        self.assertEqual(
            payload["owner_next_actions"],
            [
                {
                    "owner": "worker",
                    "channel": "linkedin",
                    "pending_channels": ["linkedin"],
                    "pending_count": 1,
                    "next_action": "create_social_post_brief",
                    "safe_next_step": (
                        "create facts-only social_post brief for linkedin; "
                        "copywriter authors external prose before claim/publish"
                    ),
                    "source": "expansion",
                    "oldest_blocked_days": None,
                }
            ],
        )

    def test_distribution_sku1_gate_recommends_claiming_approved_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            copy_file = Path(tmpdir) / "linkedin.md"
            approved_copy_dir.joinpath("sku1-linkedin-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "linkedin",
                        "copy_file": str(copy_file),
                        "thread_ref": (
                            "distribution sku1-gate channel=linkedin; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "claim_approved_copy")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "linkedin",
                "source": "approved_copy",
                "owner": "worker_browser",
                "next_action": "claim_approved_copy",
                "safe_next_step": (
                    f"claim linkedin with approved copy_file={copy_file}, "
                    "publish once, then record receipt; login/2FA/CAPTCHA=STOP"
                ),
                "reason": "copywriter_approved_copy_pending_publication",
                "copy_file": str(copy_file),
                "copy_source": str(approved_copy_dir / "sku1-linkedin-social-post.json"),
            },
        )
        self.assertTrue(payload["channel_conversion_plan"]["ready_to_publish"])
        self.assertFalse(payload["channel_execution_packet"]["copywriter_required"])
        self.assertEqual(payload["channel_execution_packet"]["copy_file"], str(copy_file))
        self.assertEqual(
            payload["publish_post_commands"]["claim_command"],
            "python3 opportunity-desk/scripts/publish_post.py claim "
            f"--channel linkedin --copy-file {copy_file}",
        )
        self.assertEqual(payload["approved_copy"][0]["channel"], "linkedin")

    def test_distribution_sku1_gate_unblocks_copywriter_receipt_with_approved_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("devto-20260624T093400Z.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file for channel",
                        "ts_blocked": "2026-06-24T09:34:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            copy_file = Path(tmpdir) / "devto.md"
            approved_copy_dir.joinpath("sku1-devto-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "devto",
                        "copy_file": str(copy_file),
                        "thread_ref": "distribution sku1-gate channel=devto",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommended_channel"]["channel"], "devto")
        self.assertEqual(payload["recommended_channel"]["next_action"], "claim_approved_copy")
        self.assertEqual(payload["recommended_channel"]["owner"], "worker")
        self.assertEqual(payload["recommended_channel"]["copy_file"], str(copy_file))
        self.assertEqual(payload["blocker_owner_counts"], {"worker": 1})
        self.assertFalse(payload["channel_execution_packet"]["copywriter_required"])

    def test_distribution_sku1_gate_does_not_recommend_posted_expansion_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("linkedin.json").write_text(
                json.dumps(
                    {
                        "channel": "linkedin",
                        "status": "posted",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:123",
                        "ts_posted": "2026-06-25T14:22:03Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            approved_copy_dir.joinpath("sku1-linkedin-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "linkedin",
                        "copy_file": str(Path(tmpdir) / "linkedin.md"),
                        "thread_ref": "distribution sku1-gate channel=linkedin",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertIsNone(payload["recommended_channel"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(payload["traffic_execution_plan"]["recommended_channel"], None)
        self.assertEqual(payload["covered_channel_plan"]["next_channel"], None)
        self.assertEqual(
            payload["channel_closeout_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "all_channels_covered": True,
                "covered_channels": 6,
                "total_channels": 6,
                "next_action": "preflight_guarded_ads_or_measure_gate",
                "safe_next_step": (
                    "Run the ad_spend_guard preflight before any paid boost; if no logged-in "
                    "eligible ad account is available, record measurement and wait for the next signal."
                ),
                "paid_preflight_command": (
                    "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                    "--amount 75.00 --platform sku1-traffic-boost "
                    "--campaign ci-triage-sku1-gate"
                ),
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
            },
        )
        self.assertEqual(
            payload["paid_ad_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "owner": "worker",
                "platform": "sku1-traffic-boost",
                "campaign": "ci-triage-sku1-gate",
                "amount_usd": 75.0,
                "paid_click_target": 100,
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=guarded_paid_boost&utm_campaign=ci-triage-sku1-gate"
                ),
                "preflight_command": (
                    "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                    "--amount 75.00 --platform sku1-traffic-boost "
                    "--campaign ci-triage-sku1-gate"
                ),
                "eligibility_required": True,
                "spend_executable": False,
                "ad_account_eligibility": {
                    "source": "not_provided",
                    "proof_path": "",
                    "platform": "sku1-traffic-boost",
                    "eligible": False,
                    "reason": "missing_logged_in_preexisting_ad_account_proof",
                    "required_fields": [
                        "platform",
                        "logged_in",
                        "preexisting_account",
                        "card_on_file",
                    ],
                },
                "commit_command_template": "",
                "fallback_action": "measure_gate_until_eligible_ad_account",
                "halt_flag": "~/.openclaw/run/AD_SPEND_HALT.flag",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd,"
                    ".ad_spend_committed_usd,.ad_cap_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
                "safe_next_step": (
                    "Measure the gate until a logged-in preexisting ad account with card-on-file "
                    "is proven; do not create accounts, add cards, bypass login, or spend from "
                    "unproven eligibility."
                ),
            },
        )
        self.assertEqual(
            payload["measurement_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "as_of": "2026-06-25",
                "gate_date": "2026-06-30",
                "traffic_delivered": 28,
                "traffic_target": 300,
                "traffic_gap": 272,
                "sales_total": 0,
                "gross_usd": 0.0,
                "days_to_gate": 5,
                "required_daily_traffic": 54.4,
                "ad_remaining_usd": 75.0,
                "paid_click_capacity": 100,
                "paid_boost_blocked_reason": "missing_logged_in_preexisting_ad_account_proof",
                "next_measurement_command": (
                    "jq '.traffic_delivered_total,.pivot_gate_armed,.pivot_gate_fires,"
                    ".gumroad_sales_total,.gumroad_gross_usd,.replies_detected,"
                    ".ad_spend_committed_usd,.ad_cap_usd' "
                    "~/.openclaw/run/patchrail_supervisor_last.json"
                ),
                "safe_next_step": (
                    "Measure visits and sales until SKU #1 reaches 300 visits before 2026-06-30, "
                    "or until a proven eligible ad account makes the guarded boost executable."
                ),
            },
        )
        self.assertIn("posted", payload["covered_channel_plan"]["status_counts"])
        self.assertEqual(
            [
                (item["channel"], item["status"], item["recommended"])
                for item in payload["covered_channel_plan"]["channels"]
                if item["channel"] == "linkedin"
            ],
            [("linkedin", "posted", False)],
        )

    def test_distribution_sku1_gate_marks_paid_boost_executable_with_eligibility_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("linkedin.json").write_text(
                json.dumps(
                    {
                        "channel": "linkedin",
                        "status": "posted",
                        "url": "https://www.linkedin.com/posts/patchrail",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "preflight_guarded_ads_or_measure_gate")
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertTrue(packet["spend_executable"])
        self.assertEqual(packet["fallback_action"], "")
        self.assertEqual(
            packet["ad_account_eligibility"]["reason"], "eligible_preexisting_logged_in_account"
        )
        self.assertIn("--amount 75.00", packet["commit_command_template"])

    def test_distribution_sku1_gate_fires_only_after_target_and_gate_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "300",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-30",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["pivot_gate_armed"])
        self.assertTrue(payload["pivot_gate_fires"])
        self.assertEqual(payload["next_action"], "pivot_offer")
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 0)
        self.assertEqual(payload["traffic_execution_plan"]["organic_click_target"], 0)

    def test_distribution_sku1_gate_writes_social_copy_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )
            brief_path = Path(tmpdir) / "requests" / "sku1-devto-social-post.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                        "--write-copy-brief",
                        str(brief_path),
                    ]
                )
            brief = json.loads(brief_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["copy_brief_write"]["status"], "written")
            self.assertEqual(payload["copy_brief_write"]["path"], str(brief_path))
            self.assertTrue(payload["copy_brief_write"]["forbidden_fields_absent"])
        self.assertEqual(brief["type"], "social_post")
        self.assertEqual(brief["channel"], "devto")
        self.assertEqual(brief["lead"], "SKU #1 CI Triage $19")
        self.assertIn("utm_source=devto", brief["thread_ref"])
        self.assertNotIn("body", brief)
        self.assertNotIn("draft", brief)
        self.assertNotIn("email_body", brief)

    def test_ci_classify_emits_json_without_external_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "patchrail.ci_result.v1")
            self.assertEqual(payload["failure_class"], "python_test_failure")
            self.assertEqual(payload["requirements"]["billing_required"], False)
            self.assertEqual(payload["requirements"]["external_model_required"], False)
            self.assertIn("pytest", payload["reproduction_command"])

    def test_ci_classify_detects_runner_memory_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pytest -q\n"
                "collected 412 items\n"
                "##[error]The operation was canceled.\n"
                "Process completed with exit code 137.\n"
                "Container app was OOMKilled (exceeded memory limit).\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "runner_resource_exhaustion")
            self.assertEqual(payload["requirements"]["external_model_required"], False)
            self.assertIn("memory", payload["minimal_repair_strategy"])

    def test_ci_classify_detects_runner_disk_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "npm error code ENOSPC\n"
                "npm error syscall write\n"
                "npm error errno -28\n"
                "npm error nospc ENOSPC: No space left on device, write\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "runner_resource_exhaustion")
            self.assertIn("disk", payload["minimal_repair_strategy"])

    def test_ci_classify_detects_dns_network_transient_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run python -m pip install -r requirements.txt\n"
                "WARNING: Retrying after connection broken by 'NewConnectionError'\n"
                "Could not resolve host: pypi.org\n"
                "Temporary failure in name resolution\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")
            self.assertIn("retry", payload["minimal_repair_strategy"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_transient_registry_outage_wins_over_install_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "npm ERR! code E503\n"
                "npm ERR! 503 Service Unavailable - GET https://registry.npmjs.org/react\n"
                "npm ERR! Connection reset by peer\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")

    def test_ci_classify_detects_git_network_transient_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run actions/checkout@v4\n"
                "fatal: unable to access 'https://github.com/org/repo/': "
                "Failed to connect to github.com port 443: Connection timed out\n"
                "The remote end hung up unexpectedly\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")
            self.assertIn("re-run", payload["reproduction_command"])

    def test_ci_classify_detects_github_actions_job_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run python -m pytest -q\n"
                "The job running on runner GitHub Actions 12 has exceeded "
                "the maximum execution time of 360 minutes.\n"
                "##[error]The operation was canceled.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")
            self.assertIn("time limit", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_gitlab_job_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Running with gitlab-runner 17.4.0\n"
                "ERROR: Job failed: execution took longer than 1h0m0s seconds\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_circleci_no_output_timeout_wins_over_network_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Too long with no output (exceeded 10m0s): context deadline exceeded\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_job_timeout_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\n"
                "tests/test_app.py ........................                [ 64%]\n"
                "The job running on runner ubuntu-latest-8core has exceeded "
                "the maximum execution time of 90 minutes.\n"
                "##[error]The operation was canceled.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_detects_pytest_coverage_threshold_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pytest --cov=src --cov-fail-under=90\n"
                "======================== 412 passed in 18.44s ========================\n"
                "Required test coverage of 90% not reached. Total coverage: 86.71%\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")
            self.assertIn("coverage", payload["minimal_repair_strategy"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_coverage_gate_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "coverage report --fail-under=85\n"
                "Coverage failure: total of 82 is less than fail-under=85\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")

    def test_ci_classify_detects_jest_coverage_threshold_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                'Jest: "global" coverage threshold for statements (90%) not met: 84.21%\n'
                "Jest: Coverage for lines (88%) does not meet global threshold (90%)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")

    def test_ci_classify_detects_mypy_type_check_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run mypy src\n"
                'src/app.py:42: error: Incompatible return value type (got "int", '
                'expected "str")  [return-value]\n'
                'src/app.py:88: error: Argument 1 to "run" has incompatible type '
                '"bytes"; expected "str"  [arg-type]\n'
                "Found 2 errors in 1 file (checked 24 source files)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")
            self.assertGreaterEqual(payload["confidence"], 0.7)
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_pyright_type_check_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pyright\n"
                '/repo/src/app.py:17:9 - error: "value" is not assignable to declared '
                'type "int" (reportAssignmentType)\n'
                "3 errors, 0 warnings, 0 informations\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")

    def test_ci_classify_type_check_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run: pytest && mypy src\n"
                "============== 120 passed in 4.2s ==============\n"
                "src/app.py:10: error: Incompatible types in assignment  [assignment]\n"
                "Found 1 error in 1 file (checked 12 source files)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")

    def test_ci_classify_detects_ruff_lint_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run ruff check .\n"
                "src/app.py:1:1: F401 [*] `os` imported but unused\n"
                "src/app.py:12:89: E501 Line too long (104 > 88)\n"
                "Found 2 errors.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["failure_class"], "python_lint")
        self.assertGreaterEqual(payload["confidence"], 0.7)
        self.assertEqual(
            payload["guide_url"],
            "https://getpatchrail.com/fix/python-lint?utm_source=cli&utm_campaign=python-lint",
        )
        self.assertEqual(
            payload["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=python-lint",
        )
        self.assertEqual(
            payload["action_url"],
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-lint",
        )

    def test_ci_classify_detects_black_format_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run black --check .\n"
                "would reformat src/app.py\n"
                "Oh no! 1 file would be reformatted, 23 files would be left unchanged.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_lint")

    def test_schema_command_emits_ci_result_contract(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "schema", "ci-result"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        schema = json.loads(proc.stdout)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "patchrail.ci_result.v1")
        self.assertIn("python_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("java_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("dotnet_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("docker_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("browser_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("security_scan_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("ruby_bundle_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("php_composer_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("runner_resource_exhaustion", schema["properties"]["failure_class"]["enum"])
        self.assertIn("network_transient_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("code_coverage_threshold", schema["properties"]["failure_class"]["enum"])
        self.assertIn("python_type_check", schema["properties"]["failure_class"]["enum"])
        self.assertIn("python_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("ci_job_timeout", schema["properties"]["failure_class"]["enum"])
        self.assertIn("cpp_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("guide_url", schema["required"])
        self.assertIn("pack_url", schema["required"])
        self.assertIn("action_url", schema["required"])
        self.assertEqual(
            schema["properties"]["guide_url"]["pattern"],
            "^https://getpatchrail\\.com/fix",
        )
        self.assertEqual(
            schema["properties"]["pack_url"]["pattern"],
            "^https://patchrail\\.gumroad\\.com/l/ci-failure-triage",
        )
        self.assertEqual(
            schema["properties"]["action_url"]["pattern"],
            "^https://github\\.com/patchrail/ci-triage-action",
        )
        self.assertIn("node_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("node_dependency_install", schema["properties"]["failure_class"]["enum"])
        self.assertIn("rust_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("go_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("typescript_typecheck", schema["properties"]["failure_class"]["enum"])
        self.assertEqual(
            schema["properties"]["requirements"]["properties"]["billing_required"]["const"], False
        )
        self.assertEqual(
            schema["properties"]["requirements"]["properties"]["external_model_required"]["const"],
            False,
        )

    def test_schema_command_emits_ci_benchmark_and_pilot_contracts(self) -> None:
        expected_versions = {
            "application-dossier": "patchrail.application_dossier.v1",
            "ci-benchmark": "patchrail.ci_benchmark.v1",
            "ci-fixture-check": "patchrail.ci_fixture_check.v1",
            "ci-pilot-summary": "patchrail.ci_pilot_summary.v1",
            "ci-pilot-metrics": "patchrail.ci_pilot_metrics.v1",
            "reviewer-quick-check-artifacts": "patchrail.reviewer_quick_check_artifacts.v1",
        }

        for schema_name, schema_version in expected_versions.items():
            with self.subTest(schema_name=schema_name):
                proc = subprocess.run(
                    [sys.executable, "-m", "patchrail", "schema", schema_name],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(proc.returncode, 0, proc.stderr)
                schema = json.loads(proc.stdout)
                self.assertEqual(schema["properties"]["schema_version"]["const"], schema_version)
                if schema_name == "application-dossier":
                    submission = schema["properties"]["submission_policy"]["properties"]
                    safety = schema["properties"]["safety"]["properties"]
                    self.assertEqual(submission["maintainer_tap_required"]["const"], True)
                    self.assertEqual(submission["agent_may_submit"]["const"], False)
                    self.assertEqual(submission["no_placeholder_metrics"]["const"], True)
                    self.assertEqual(submission["no_money_goal"]["const"], True)
                    self.assertEqual(safety["local_first"]["const"], True)
                    self.assertEqual(safety["billing_required"]["const"], False)
                    self.assertEqual(safety["third_party_write_actions_allowed"]["const"], False)
                elif schema_name == "reviewer-quick-check-artifacts":
                    self.assertEqual(
                        schema["properties"]["generated_from"]["const"], "local_checkout"
                    )
                    self.assertEqual(schema["properties"]["network_required"]["const"], False)
                    self.assertEqual(schema["properties"]["write_action_required"]["const"], False)
                    self.assertEqual(
                        schema["properties"]["application_form_submission_performed"]["const"],
                        False,
                    )
                    artifacts = schema["properties"]["artifacts"]["items"]["enum"]
                    self.assertIn("README.md", artifacts)
                    self.assertIn("reviewer-quick-check.md", artifacts)
                    self.assertIn("application-dossier.json", artifacts)
                    self.assertIn("http-api-evidence.json", artifacts)
                    self.assertIn("http-api-evidence.md", artifacts)
                    self.assertIn("release-readiness.json", artifacts)
                    self.assertIn("release-readiness.md", artifacts)
                    self.assertIn("reviewer-quick-check-artifacts.schema.json", artifacts)
                else:
                    requirements = schema["properties"]["requirements"]["properties"]
                    self.assertEqual(requirements["billing_required"]["const"], False)
                    self.assertEqual(requirements["external_model_required"]["const"], False)
                    self.assertEqual(requirements["network_required"]["const"], False)
                    if "github_write_permission_required" in requirements:
                        self.assertEqual(
                            requirements["github_write_permission_required"]["const"], False
                        )

    def test_doctor_reports_local_first_requirements(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "doctor", "--format", "json"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.doctor.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["local_first"], True)
        self.assertEqual(payload["checks"]["ci_fixture_count"], 153)
        self.assertEqual(payload["checks"]["ci_result_schema_available"], True)
        self.assertEqual(payload["requirements"]["billing_required"], False)
        self.assertEqual(payload["requirements"]["external_model_required"], False)
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_ci_benchmark_checks_fixture_expectations(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.ci_benchmark.v1")
        self.assertEqual(payload["total_cases"], 153)
        self.assertEqual(payload["passed"], 153)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["accuracy"]["top_1"], 1.0)
        self.assertEqual(payload["coverage_gate"]["min_cases_per_class"], 0)
        self.assertEqual(payload["coverage_gate"]["passed"], True)
        self.assertEqual(payload["coverage_gate"]["failures"], [])
        self.assertEqual(payload["root"], "examples/ci-triage")
        self.assertEqual(
            payload["class_summary"],
            {
                "browser_test_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "dotnet_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "docker_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "github_actions_workflow": {"failed": 0, "passed": 10, "total_cases": 10},
                "go_test_failure": {"failed": 0, "passed": 10, "total_cases": 10},
                "java_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "javascript_lint": {"failed": 0, "passed": 11, "total_cases": 11},
                "node_dependency_install": {"failed": 0, "passed": 19, "total_cases": 19},
                "php_composer_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "python_dependency_resolution": {"failed": 0, "passed": 27, "total_cases": 27},
                "python_test_failure": {"failed": 0, "passed": 9, "total_cases": 9},
                "ruby_bundle_failure": {"failed": 0, "passed": 8, "total_cases": 8},
                "rust_test_failure": {"failed": 0, "passed": 10, "total_cases": 10},
                "security_scan_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "typescript_typecheck": {"failed": 0, "passed": 19, "total_cases": 19},
            },
        )
        actual_classes = {case["actual_failure_class"] for case in payload["cases"]}
        self.assertEqual(
            actual_classes,
            {
                "browser_test_failure",
                "dotnet_build_failure",
                "docker_build_failure",
                "github_actions_workflow",
                "go_test_failure",
                "java_build_failure",
                "javascript_lint",
                "node_dependency_install",
                "php_composer_failure",
                "python_dependency_resolution",
                "python_test_failure",
                "ruby_bundle_failure",
                "rust_test_failure",
                "security_scan_failure",
                "typescript_typecheck",
            },
        )
        self.assertEqual(payload["requirements"]["network_required"], False)

    def test_ci_benchmark_summary_only_omits_case_details(self) -> None:
        json_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(json_proc.returncode, 0, json_proc.stderr)
        payload = json.loads(json_proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.ci_benchmark.v1")
        self.assertEqual(payload["total_cases"], 153)
        self.assertEqual(payload["passed"], 153)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["accuracy"]["top_1"], 1.0)
        self.assertEqual(payload["coverage_gate"]["passed"], True)
        self.assertIn("class_summary", payload)
        self.assertIn("coverage_gate", payload)
        self.assertNotIn("cases", payload)

        markdown_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "markdown",
                "--summary-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(markdown_proc.returncode, 0, markdown_proc.stderr)
        self.assertIn("# PatchRail CI Benchmark", markdown_proc.stdout)
        self.assertIn("- Total cases: `153`", markdown_proc.stdout)
        self.assertIn("- Coverage gate passed: `True`", markdown_proc.stdout)
        self.assertIn("## Class summary", markdown_proc.stdout)
        self.assertNotIn("## Cases", markdown_proc.stdout)

    def test_ci_benchmark_coverage_gate_can_require_depth_per_class(self) -> None:
        pass_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
                "--min-cases-per-class",
                "5",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(pass_proc.returncode, 0, pass_proc.stderr)
        pass_payload = json.loads(pass_proc.stdout)
        self.assertEqual(pass_payload["coverage_gate"]["min_cases_per_class"], 5)
        self.assertEqual(pass_payload["coverage_gate"]["passed"], True)
        self.assertEqual(pass_payload["coverage_gate"]["failures"], [])

        fail_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
                "--min-cases-per-class",
                "6",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(fail_proc.returncode, 1)
        fail_payload = json.loads(fail_proc.stdout)
        self.assertEqual(fail_payload["failed"], 0)
        self.assertEqual(fail_payload["coverage_gate"]["passed"], False)
        failing_classes = {
            failure["failure_class"]: failure
            for failure in fail_payload["coverage_gate"]["failures"]
        }
        self.assertEqual(failing_classes["browser_test_failure"]["total_cases"], 5)
        self.assertEqual(failing_classes["browser_test_failure"]["minimum_cases"], 6)

    def test_ci_benchmark_rejects_negative_coverage_gate(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--min-cases-per-class",
                "-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("--min-cases-per-class must be >= 0", proc.stderr)

    def test_ci_fixture_check_accepts_clean_fixture_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "python-test.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "python_test_failure", "minimum_confidence": 0.7}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_fixture_check.v1")
            self.assertEqual(payload["total_cases"], 1)
            self.assertEqual(payload["passed"], 1)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["requirements"]["network_required"], False)
            self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_ci_classify_detects_docker_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "docker.log"
            log.write_text(
                "docker buildx build --target runtime .\n"
                'ERROR: failed to solve: target stage "runtime" could not be found\n',
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "docker_build_failure")
            self.assertIn("docker build", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_cmake_build_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "CMake Error at CMakeLists.txt:42 (find_package)\n"
                "ninja: build stopped: subcommand failed.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")
            self.assertIn("cmake --build", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_gcc_link_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "app.o: in function `main': undefined reference to `foo::bar()'\n"
                "collect2: error: ld returned 1 exit status\n"
                "make: *** [app] Error 1\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_detects_clang_compile_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "src/widget.cpp:18:5: error: use of undeclared identifier 'widget'\n"
                "clang++: error: unable to execute command: linker command failed\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_cpp_header_failure_wins_over_docker_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "src/widget.cpp:3:10: fatal error: widget.h: No such file or directory\n"
                "make: *** [obj/widget.o] Error 1\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_detects_browser_test_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "playwright.log"
            log.write_text(
                "npx playwright test\n"
                "Error: browserType.launch: Executable doesn't exist at <cache>/chromium/chrome\n"
                "Please run npx playwright install\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "browser_test_failure")
            self.assertIn("playwright", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_java_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "java.log"
            log.write_text(
                "Run mvn -B test\n"
                "[ERROR] COMPILATION ERROR :\n"
                "[ERROR] cannot find symbol\n"
                "[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "java_build_failure")
            self.assertIn("gradlew", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_dotnet_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "dotnet.log"
            log.write_text(
                "Run dotnet restore src/App/App.csproj\n"
                "error NU1107: Version conflict detected for Microsoft.Extensions.Logging.\n"
                "Install/reference Microsoft.Extensions.Logging 8.0.0 directly to project.\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "dotnet_build_failure")
            self.assertIn("dotnet restore", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_ruby_bundle_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "ruby.log"
            log.write_text(
                "Run bundle install\n"
                'Bundler could not find compatible versions for gem "rack":\n'
                "  In Gemfile:\n"
                "    rails was resolved to 7.1.0, which depends on rack (~> 2.2)\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "ruby_bundle_failure")
            self.assertIn("bundle install", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_php_composer_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "php.log"
            log.write_text(
                "Run composer install --no-interaction --prefer-dist\n"
                "Your requirements could not be resolved to an installable set of packages.\n"
                "Problem 1\n"
                "Root composer.json requires php ^8.3 but your php version (8.2.14) does not satisfy that requirement.\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "php_composer_failure")
            self.assertIn("composer install", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_fixture_check_fails_for_missing_expected_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "missing-metadata.log"
            log.write_text("cargo test\nthread 'demo' panicked\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("missing neighboring .expected.json file", payload["cases"][0]["issues"])

    def test_ci_fixture_check_fails_for_unredacted_sensitive_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "unredacted.log"
            log.write_text(
                "python -m pytest -q\n"
                "FAILED tests/test_app.py::test_ok - AssertionError\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "python_test_failure", "minimum_confidence": 0.7}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("email", payload["cases"][0]["redactions"])
            self.assertIn("mac_home_path", payload["cases"][0]["redactions"])
            self.assertIn("possible unredacted sensitive data", payload["cases"][0]["issues"][0])

    def test_ci_fixture_check_flags_registry_tokens_and_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "unredacted-windows.log"
            log.write_text(
                "npm audit\n"
                "1 critical severity vulnerability\n"
                "npm token npm_1234567890abcdefghijklmnopqrst\n"
                "Path C:\\Users\\runner\\work\\repo\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "security_scan_failure", "minimum_confidence": 0.5}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("npm_token", payload["cases"][0]["redactions"])
            self.assertIn("windows_home_path", payload["cases"][0]["redactions"])
            self.assertTrue(
                any(
                    "possible unredacted sensitive data" in issue
                    for issue in payload["cases"][0]["issues"]
                )
            )

    def test_ci_explain_defaults_to_markdown_and_states_safety_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--log", str(log)])

            markdown = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("# PatchRail CI Report", markdown)
            self.assertIn("python_dependency_resolution", markdown)
            self.assertIn("did not create a pull request", markdown)
            self.assertIn("send data to an external service", markdown)

    def test_module_entrypoint_runs_public_cli(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "ci", "classify"],
            input="cargo test\nthread 'demo' panicked\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["failure_class"], "rust_test_failure")
        self.assertEqual(
            payload["guide_url"],
            "https://getpatchrail.com/fix/rust-test-failure"
            "?utm_source=cli&utm_campaign=rust-test-failure",
        )
        self.assertEqual(
            payload["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=rust-test-failure",
        )

    def test_ci_explain_redacts_secret_values_from_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            fake_github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
            log.write_text(
                "python -m pytest -q\n"
                "FAILED tests/test_app.py::test_ok - AssertionError\n"
                f"GITHUB_TOKEN={fake_github_token}\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--redact", "--log", str(log)])

            markdown = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("## Redaction", markdown)
            self.assertIn("env_secret_assignment", markdown)
            self.assertIn("email", markdown)
            self.assertIn("mac_home_path", markdown)
            self.assertNotIn(fake_github_token, markdown)
            self.assertNotIn("maintainer@example.com", markdown)
            self.assertNotIn("/Users/example", markdown)

    def test_ci_pilot_pack_generates_local_redacted_consent_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            fake_github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n"
                f"GITHUB_TOKEN={fake_github_token}\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["schema_version"], "patchrail.ci_pilot_pack_result.v1")
            self.assertEqual(summary["requirements"]["network_required"], False)
            self.assertEqual(summary["requirements"]["github_write_permission_required"], False)
            self.assertIn("open_pull_request", summary["blocked_actions"])
            self.assertIn("contact_maintainer", summary["blocked_actions"])

            manifest = json.loads((out_dir / "pilot-manifest.json").read_text(encoding="utf-8"))
            result = json.loads((out_dir / "patchrail-result.json").read_text(encoding="utf-8"))
            redacted_log = (out_dir / "failed-ci.redacted.log").read_text(encoding="utf-8")
            report = (out_dir / "patchrail-report.md").read_text(encoding="utf-8")
            readme = (out_dir / "README.md").read_text(encoding="utf-8")

            self.assertEqual(manifest["schema_version"], "patchrail.ci_pilot_pack.v1")
            self.assertEqual(manifest["source"]["source_log_name"], "failed-ci.log")
            self.assertEqual(manifest["source"]["raw_log_copied"], False)
            self.assertEqual(
                manifest["classification"]["failure_class"], "python_dependency_resolution"
            )
            self.assertEqual(result["failure_class"], "python_dependency_resolution")
            self.assertEqual(
                result["guide_url"],
                "https://getpatchrail.com/fix/python-dependency-resolution"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                result["pack_url"],
                "https://patchrail.gumroad.com/l/ci-failure-triage"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                result["action_url"],
                "https://github.com/patchrail/ci-triage-action"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                manifest["consent_boundary"]["maintainer_review_required_before_sharing"], True
            )
            self.assertEqual(
                manifest["consent_boundary"]["repository_write_access_required"], False
            )
            self.assertEqual(manifest["requirements"]["external_model_required"], False)

            serialized = "\n".join([redacted_log, report, readme, json.dumps(manifest)])
            self.assertIn("python_dependency_resolution", serialized)
            self.assertIn("PatchRail did not copy the raw log", readme)
            self.assertIn("Share only after a maintainer reviews", readme)
            self.assertNotIn(fake_github_token, serialized)
            self.assertNotIn("maintainer@example.com", serialized)
            self.assertNotIn("/Users/example", serialized)
            self.assertIn("GITHUB_TOKEN=<redacted>", redacted_log)
            self.assertIn("<email>", redacted_log)
            self.assertIn("/Users/<user>/project", redacted_log)

    def test_ci_pilot_summary_defaults_to_private_repository_mention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n",
                encoding="utf-8",
            )
            pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(pack_proc.returncode, 0, pack_proc.stderr)

            summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(out_dir),
                    "--repository",
                    "private-owner/private-repo",
                    "--ci-provider",
                    "GitHub Actions",
                    "--toolchain",
                    "Python",
                    "--classification-correct",
                    "yes",
                    "--maintainer-action-useful",
                    "yes",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(summary_proc.returncode, 0, summary_proc.stderr)
            self.assertIn("# PatchRail Consent-Only Pilot Summary", summary_proc.stdout)
            self.assertIn("Repository approved for public mention: `false`", summary_proc.stdout)
            self.assertIn("Repository: `not approved for public listing`", summary_proc.stdout)
            self.assertIn("Root cause: `python_dependency_resolution`", summary_proc.stdout)
            self.assertIn("Classification correct: `yes`", summary_proc.stdout)
            self.assertIn("Suggested maintainer action useful: `yes`", summary_proc.stdout)
            self.assertIn("PatchRail ran locally", summary_proc.stdout)
            self.assertIn("did not copy the raw log", summary_proc.stdout)
            self.assertNotIn("private-owner/private-repo", summary_proc.stdout)

    def test_ci_pilot_summary_json_includes_repository_only_when_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            log.write_text(
                "cargo test\nthread 'tests::demo' panicked at src/lib.rs:7\n",
                encoding="utf-8",
            )
            pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(pack_proc.returncode, 0, pack_proc.stderr)

            summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(out_dir / "pilot-manifest.json"),
                    "--repository",
                    "patchrail/example",
                    "--repository-mention-approved",
                    "yes",
                    "--ci-provider",
                    "GitHub Actions",
                    "--toolchain",
                    "Rust",
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(summary_proc.returncode, 0, summary_proc.stderr)
            payload = json.loads(summary_proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_pilot_summary.v1")
            self.assertEqual(payload["pilot_pack"]["manifest_path"], "pilot-manifest.json")
            self.assertEqual(payload["public_listing"]["repository_mention_approved"], True)
            self.assertEqual(payload["public_listing"]["repository"], "patchrail/example")
            self.assertEqual(payload["pilot_context"]["ci_provider"], "GitHub Actions")
            self.assertEqual(payload["pilot_context"]["toolchain"], "Rust")
            self.assertEqual(payload["classification"]["failure_class"], "rust_test_failure")
            self.assertEqual(payload["pilot_pack"]["raw_log_copied"], False)
            self.assertEqual(payload["requirements"]["network_required"], False)
            self.assertIn("open_pull_request", payload["blocked_actions"])
            self.assertNotIn("/Volumes/", summary_proc.stdout)
            self.assertNotIn("/Users/", summary_proc.stdout)
            self.assertNotIn("/home/", summary_proc.stdout)

    def test_ci_pilot_metrics_aggregates_public_and_private_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            first_log = root / "first.log"
            first_pack = root / "first-pack"
            first_summary = root / "first-summary.json"
            first_log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )
            first_pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(first_log),
                    "--out-dir",
                    str(first_pack),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first_pack_proc.returncode, 0, first_pack_proc.stderr)
            first_summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(first_pack),
                    "--classification-correct",
                    "yes",
                    "--maintainer-action-useful",
                    "yes",
                    "--format",
                    "json",
                    "--out",
                    str(first_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first_summary_proc.returncode, 0, first_summary_proc.stderr)

            second_log = root / "second.log"
            second_pack = root / "second-pack"
            second_summary = root / "second-summary.json"
            second_log.write_text(
                "cargo test\nthread 'tests::demo' panicked at src/lib.rs:7\n",
                encoding="utf-8",
            )
            second_pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(second_log),
                    "--out-dir",
                    str(second_pack),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_pack_proc.returncode, 0, second_pack_proc.stderr)
            second_summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(second_pack),
                    "--repository",
                    "patchrail/example",
                    "--repository-mention-approved",
                    "yes",
                    "--classification-correct",
                    "no",
                    "--maintainer-action-useful",
                    "unknown",
                    "--format",
                    "json",
                    "--out",
                    str(second_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_summary_proc.returncode, 0, second_summary_proc.stderr)

            metrics_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-metrics",
                    str(first_summary),
                    str(second_summary),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(metrics_proc.returncode, 0, metrics_proc.stderr)
            payload = json.loads(metrics_proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_pilot_metrics.v1")
            self.assertEqual(payload["total_pilot_summaries"], 2)
            self.assertEqual(payload["public_repository_mentions"], 1)
            self.assertEqual(payload["private_or_unapproved_repository_mentions"], 1)
            self.assertEqual(payload["public_repositories"], ["patchrail/example"])
            self.assertEqual(payload["owned_repository_mentions"], 1)
            self.assertEqual(payload["external_repository_mentions"], 0)
            self.assertEqual(payload["owned_repositories"], ["patchrail/example"])
            self.assertEqual(payload["external_repositories"], [])
            self.assertEqual(payload["evidence_readiness"]["status"], "owned_repo_evidence_only")
            self.assertEqual(payload["evidence_readiness"]["external_adopters_countable"], 0)
            self.assertEqual(payload["evidence_readiness"]["owned_repo_evidence_countable"], 1)
            self.assertEqual(payload["evidence_readiness"]["private_feedback_count"], 1)
            self.assertEqual(payload["classification_correct"]["yes"], 1)
            self.assertEqual(payload["classification_correct"]["no"], 1)
            self.assertEqual(payload["maintainer_action_useful"]["yes"], 1)
            self.assertEqual(payload["maintainer_action_useful"]["unknown"], 1)
            self.assertEqual(payload["local_only_and_no_raw_log"], 2)
            self.assertEqual(payload["requirements"]["network_required"], False)

            markdown_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-metrics",
                    str(first_summary),
                    str(second_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(markdown_proc.returncode, 0, markdown_proc.stderr)
            self.assertIn("# PatchRail Consent-Only Pilot Metrics", markdown_proc.stdout)
            self.assertIn("- Public repository mentions: `1`", markdown_proc.stdout)
            self.assertIn("- Owned-repo public mentions: `1`", markdown_proc.stdout)
            self.assertIn("- External public repository mentions: `0`", markdown_proc.stdout)
            self.assertIn("- Evidence readiness: `owned_repo_evidence_only`", markdown_proc.stdout)
            self.assertIn("- Countable external adopters: `0`", markdown_proc.stdout)
            self.assertIn("- `patchrail/example`", markdown_proc.stdout)
            self.assertIn("- None approved for external adopter listing.", markdown_proc.stdout)

    def test_redact_command_emits_redacted_text(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "redact"],
            input=(
                "TOKEN=secret-value\n"
                "Contact maintainer@example.com\n"
                "Path /home/runner/work\n"
                "Windows path C:\\Users\\runner\\work\\repo\n"
                "GitLab token glpat-1234567890abcdefghijkl\n"
                "PyPI token pypi-AgEIcHlwaS5vcmcCdGVzdC12YWx1ZQ\n"
                "npm token npm_1234567890abcdefghijklmnopqrst\n"
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("TOKEN=<redacted>", proc.stdout)
        self.assertIn("<email>", proc.stdout)
        self.assertIn("/home/<user>/work", proc.stdout)
        self.assertIn("C:/Users/<user>\\work\\repo", proc.stdout)
        self.assertIn("<gitlab-token>", proc.stdout)
        self.assertIn("<pypi-token>", proc.stdout)
        self.assertIn("<npm-token>", proc.stdout)
        self.assertNotIn("secret-value", proc.stdout)
        self.assertNotIn("maintainer@example.com", proc.stdout)
        self.assertNotIn("glpat-1234567890abcdefghijkl", proc.stdout)
        self.assertNotIn("pypi-AgEIcHlwaS5vcmcCdGVzdC12YWx1ZQ", proc.stdout)
        self.assertNotIn("npm_1234567890abcdefghijklmnopqrst", proc.stdout)

    def test_redact_command_handles_cloud_and_key_material(self) -> None:
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.s5b3Qd7n0pXcVm9wQ1aZ2k4L8tR6yU0o"
        fake_google_key = "AIza" + "b" * 35
        # Build at runtime so the recognizable token prefix never appears verbatim in source.
        fake_slack_token = "xox" + "b-123456789012-abcdefghijklmnop"
        private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4wggE6AgEAAkEA\n"
            "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL\n"
            "-----END RSA PRIVATE KEY-----"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "redact"],
            input=(
                f"Slack token {fake_slack_token}\n"
                f"Google key {fake_google_key}\n"
                "Google oauth ya29.A0ARrdaM-abcdefghijklmnopqrstuvwxyz0123\n"
                "HuggingFace hf_abcdefghijklmnopqrstuvwxyz0123\n"
                f"Auth header Authorization: Bearer {fake_jwt}\n"
                f"{private_key}\n"
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("<slack-token>", proc.stdout)
        self.assertIn("<google-api-key>", proc.stdout)
        self.assertIn("<google-oauth-token>", proc.stdout)
        self.assertIn("<huggingface-token>", proc.stdout)
        self.assertIn("<jwt>", proc.stdout)
        self.assertIn("<private-key>", proc.stdout)
        self.assertNotIn(fake_slack_token, proc.stdout)
        self.assertNotIn(fake_google_key, proc.stdout)
        self.assertNotIn("ya29.A0ARrdaM", proc.stdout)
        self.assertNotIn("hf_abcdefghijklmnopqrstuvwxyz0123", proc.stdout)
        self.assertNotIn(fake_jwt, proc.stdout)
        self.assertNotIn("MIIBVAIBADANBgkqhkiG", proc.stdout)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", proc.stdout)

    def test_unknown_log_is_not_repairable(self) -> None:
        result = json.loads(
            subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify"],
                input="build did not work\n",
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )

        self.assertEqual(result["failure_class"], "unknown")
        self.assertLess(result["confidence"], 0.5)
        self.assertIn("Do not auto-repair", result["minimal_repair_strategy"])
        self.assertEqual(result["guide_url"], "https://getpatchrail.com/fix?utm_source=cli")
        self.assertEqual(
            result["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=index",
        )
        self.assertEqual(
            result["action_url"],
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
        )

    def test_ci_explain_prints_fix_guide_url_for_known_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "Guide: https://getpatchrail.com/fix/python-test-failure"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )
            self.assertIn(
                "Pack: https://patchrail.gumroad.com/l/ci-failure-triage"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )
            self.assertIn(
                "Action: https://github.com/patchrail/ci-triage-action"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )

    def test_ci_explain_links_index_for_unknown_class(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "patchrail", "ci", "explain"],
            input="build did not work\n",
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("Guide: https://getpatchrail.com/fix?utm_source=cli", result.stdout)
        self.assertIn(
            "Pack: https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=index",
            result.stdout,
        )
        self.assertIn(
            "Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
            result.stdout,
        )
        self.assertNotIn("/fix/", result.stdout)


class FixGuideSlugConsistencyTests(unittest.TestCase):
    """Guard the CLI -> getpatchrail.com/fix cross-sell funnel.

    Every slug the CLI advertises a dedicated guide for must correspond to a
    real classifier failure class. If a class is renamed in classify.py without
    updating the slug set, the CLI would emit a /fix/<slug> URL that 404s on the
    site (broken link + lost conversion). This locks that invariant.
    """

    @staticmethod
    def _classifier_slugs() -> set[str]:
        return {
            rule["failure_class"].replace("_", "-")
            for rule in RULES
            if rule["failure_class"] != "unknown"
        }

    def test_every_fix_guide_slug_maps_to_a_real_failure_class(self) -> None:
        orphan_slugs = _FIX_GUIDE_SLUGS - self._classifier_slugs()
        self.assertEqual(
            orphan_slugs,
            set(),
            f"_FIX_GUIDE_SLUGS advertises /fix pages for classes the classifier "
            f"never emits (would 404 / misattribute): {sorted(orphan_slugs)}",
        )

    def test_known_slug_round_trips_to_dedicated_guide_url(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _fix_guide_url(failure_class)
            self.assertEqual(
                url,
                f"https://getpatchrail.com/fix/{slug}?utm_source=cli&utm_campaign={slug}",
            )

    def test_class_without_guide_degrades_to_index_not_a_dead_link(self) -> None:
        # pre_commit_hook_failure is a recognized class with no published /fix
        # guide (the field guide ships 31 classes). It must degrade to the index,
        # never to a /fix/<slug> page that does not exist.
        ungraded = self._classifier_slugs() - _FIX_GUIDE_SLUGS
        for slug in ungraded:
            url = _fix_guide_url(slug.replace("-", "_"))
            self.assertEqual(url, "https://getpatchrail.com/fix?utm_source=cli")
            self.assertNotIn("/fix/", url)

    def test_pack_url_uses_failure_class_campaign_for_known_guides(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _ci_triage_pack_url(failure_class)
            self.assertEqual(
                url,
                "https://patchrail.gumroad.com/l/ci-failure-triage"
                f"?utm_source=cli&utm_campaign={slug}",
            )

    def test_pack_url_uses_index_campaign_for_unknown_or_unlisted_classes(self) -> None:
        self.assertEqual(
            _ci_triage_pack_url("unknown"),
            "https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=index",
        )

    def test_action_url_uses_failure_class_campaign_for_known_guides(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _ci_triage_action_url(failure_class)
            self.assertEqual(
                url,
                f"https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign={slug}",
            )

    def test_action_url_uses_index_campaign_for_unknown_or_unlisted_classes(self) -> None:
        self.assertEqual(
            _ci_triage_action_url("unknown"),
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
        )


if __name__ == "__main__":
    unittest.main()
