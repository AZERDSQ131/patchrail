from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchrail.funded_issues import board_issue_records, board_url, parse_board_html
from patchrail.funded_issues.algora_board import approximate_age_days

NOW = "2026-06-10T12:00:00Z"


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _row(
    *,
    amount: str,
    owner: str,
    repo: str,
    number: int,
    title: str,
    age: str,
    claims: int,
    link_kind: str = "issues",
) -> str:
    claims_block = ""
    if claims:
        claims_block = f"""
        <div class="group flex cursor-pointer flex-col items-center gap-1"
             phx-click="toggle-claims" phx-value-id="abc{number}">
          <div class="flex cursor-pointer justify-center -space-x-3">
            <div><img alt="claimant" src="https://example.invalid/a.png"></div>
          </div>
          {claims} claims
        </div>"""
    return f"""
      <tr class="border-b border-white/15">
        <td class="p-4 align-middle">
          <div class="cursor-pointer font-mono text-2xl">
            <div class="font-extrabold text-emerald-300 hover:text-emerald-200">
              {amount}
            </div>
          </div>
          <a href="https://github.com/{owner}/{repo}/{link_kind}/{number}"
             class="group/issue inline-flex flex-col" rel="noopener">
            <p class="truncate text-sm font-medium text-gray-300">{repo}#{number}</p>
            <p class="line-clamp-2 break-words text-base font-medium leading-tight text-gray-100">
              {title}
            </p>
          </a>
          <p class="flex items-center gap-1.5 text-xs text-gray-400">
            {age}
          </p>
        </td>
        <td class="p-4 align-middle">{claims_block}</td>
      </tr>"""


def _board_html(rows: str, *, open_count: int = 7, completed_count: int = 12) -> str:
    return f"""<!DOCTYPE html><html><body>
      <button type="button" role="tab" phx-click="change-tab" phx-value-tab="open">
        <div class="truncate">Open</div>
        <span class="min-w-[1ch] font-mono text-emerald-200">
          {open_count}
        </span>
      </button>
      <button type="button" role="tab" phx-click="change-tab" phx-value-tab="completed">
        <div class="truncate">Completed</div>
        <span class="min-w-[1ch] font-mono text-gray-400">
          {completed_count}
        </span>
      </button>
      <table><tbody>{rows}</tbody></table>
    </body></html>"""


FIXTURE_HTML = _board_html(
    _row(
        amount="$250",
        owner="exampleorg",
        repo="widgets",
        number=42,
        title="Fix &amp; verify the widget exporter",
        age="3 weeks ago",
        claims=2,
    )
    + _row(
        amount="$1,250",
        owner="exampleorg",
        repo="gadgets",
        number=7,
        title="Large refactor bounty",
        age="2 days ago",
        claims=0,
    )
    + _row(
        amount="$75",
        owner="exampleorg",
        repo="widgets",
        number=99,
        title="Contested cleanup task",
        age="14 months ago",
        claims=5,
    )
    + _row(
        amount="$60",
        owner="SecureBananaLabs",
        repo="trap",
        number=9,
        title="Too-good-to-be-true bounty",
        age="1 week ago",
        claims=0,
    )
    + _row(
        amount="$20",
        owner="exampleorg",
        repo="widgets",
        number=5,
        title="Bounty attached to a pull request",
        age="1 month ago",
        claims=0,
        link_kind="pull",
    )
)


class ParseBoardHtmlTests(unittest.TestCase):
    def test_parses_rows_tabs_and_amounts(self) -> None:
        board = parse_board_html(FIXTURE_HTML, "exampleorg")
        self.assertEqual(board["org"], "exampleorg")
        self.assertEqual(board["source_url"], "https://algora.io/exampleorg/bounties")
        self.assertEqual(board["open_count"], 7)
        self.assertEqual(board["completed_count"], 12)
        # The pull-request row carries no issue link, so it is skipped, not guessed.
        self.assertEqual(len(board["bounties"]), 4)
        first = board["bounties"][0]
        self.assertEqual(first["repository"], "exampleorg/widgets")
        self.assertEqual(first["issue_number"], 42)
        self.assertEqual(first["url"], "https://github.com/exampleorg/widgets/issues/42")
        self.assertEqual(first["title"], "Fix & verify the widget exporter")
        self.assertEqual(first["amount_usd"], 250.0)
        self.assertEqual(first["age"], {"text": "3 weeks ago", "approx_days": 21})
        self.assertEqual(first["attempt_count"], 2)
        second = board["bounties"][1]
        self.assertEqual(second["amount_usd"], 1250.0)
        self.assertEqual(second["attempt_count"], 0)
        self.assertEqual(second["age"]["approx_days"], 2)
        self.assertEqual(board["visible_usd_total"], 1635.0)
        self.assertTrue(board["server_rendered_rows_only"])

    def test_rejects_pages_without_board_scaffolding(self) -> None:
        with self.assertRaises(ValueError):
            parse_board_html("<html><body>Log in to continue</body></html>", "exampleorg")

    def test_age_approximation(self) -> None:
        self.assertEqual(approximate_age_days("3 weeks ago"), 21)
        self.assertEqual(approximate_age_days("14 months ago"), 420)
        self.assertEqual(approximate_age_days("1 year ago"), 365)
        self.assertEqual(approximate_age_days("5 hours ago"), 0)
        self.assertIsNone(approximate_age_days("just now"))


class BoardIssueRecordsTests(unittest.TestCase):
    def test_records_carry_verified_funding_and_board_evidence(self) -> None:
        board = parse_board_html(FIXTURE_HTML, "exampleorg")
        records = board_issue_records(board, retrieved_at=NOW)
        self.assertEqual(len(records), 4)
        record = {row["reference"]: row for row in records}["exampleorg/widgets#42"]
        self.assertEqual(record["platform"], "algora")
        self.assertEqual(record["funding"]["amount"], 250.0)
        self.assertEqual(record["funding"]["currency"], "USD")
        self.assertEqual(record["funding"]["verified"], True)
        self.assertEqual(record["funding"]["evidence_url"], board_url("exampleorg"))
        self.assertEqual(record["attempt_count"], 2)
        self.assertEqual(record["posted"], {"text": "3 weeks ago", "approx_days": 21})
        self.assertEqual(
            record["board"],
            {"org": "exampleorg", "source": "algora_board", "retrieved_at": NOW},
        )
        self.assertEqual(record["opportunity_state"], "active")
        self.assertIn("score", record)
        self.assertTrue(record["read_only"])

    def test_contested_flag_follows_declared_claims(self) -> None:
        board = parse_board_html(FIXTURE_HTML, "exampleorg")
        records = board_issue_records(board, retrieved_at=NOW)
        by_reference = {record["reference"]: record for record in records}
        self.assertIn("contested_bounty", by_reference["exampleorg/widgets#99"]["risk_flags"])
        self.assertNotIn("contested_bounty", by_reference["exampleorg/widgets#42"]["risk_flags"])


class ImportAlgoraBoardCliTests(unittest.TestCase):
    def test_import_emits_payload_without_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "board.html"
            html_path.write_text(FIXTURE_HTML, encoding="utf-8")
            proc = run_patchrail(
                [
                    "funded-issues",
                    "import-algora-board",
                    "--html",
                    str(html_path),
                    "--org",
                    "exampleorg",
                    "--now",
                    NOW,
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.funded_issues.algora_board.v1")
            self.assertEqual(payload["org"], "exampleorg")
            self.assertEqual(payload["open_count"], 7)
            self.assertEqual(payload["visible_rows"], 4)
            self.assertEqual(payload["retrieved_at"], NOW)
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["requirements"]["network_required"], False)
            self.assertNotIn("store", payload)

    def test_import_merges_into_store_and_blocks_blocklisted_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "board.html"
            html_path.write_text(FIXTURE_HTML, encoding="utf-8")
            store_path = Path(tmp) / "store.json"
            args = [
                "funded-issues",
                "import-algora-board",
                "--html",
                str(html_path),
                "--org",
                "exampleorg",
                "--store",
                str(store_path),
                "--now",
                NOW,
                "--format",
                "json",
            ]
            proc = run_patchrail(args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["store"]["summary"]["added"], 3)
            self.assertEqual(payload["store"]["summary"]["blocked"], 1)
            self.assertEqual(payload["store"]["total_entries"], 3)
            saved = json.loads(store_path.read_text("utf-8"))
            self.assertNotIn("https://github.com/SecureBananaLabs/trap/issues/9", saved["entries"])
            entry = saved["entries"]["https://github.com/exampleorg/widgets/issues/42"]
            self.assertEqual(entry["issue"]["funding"]["verified"], True)
            self.assertEqual(entry["issue"]["attempt_count"], 2)

            again = run_patchrail(args)
            self.assertEqual(again.returncode, 0, again.stderr)
            payload = json.loads(again.stdout)
            self.assertEqual(payload["store"]["summary"]["added"], 0)
            self.assertEqual(payload["store"]["summary"]["unchanged"], 3)

    def test_import_rejects_non_board_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "login.html"
            html_path.write_text("<html><body>Log in</body></html>", encoding="utf-8")
            proc = run_patchrail(
                [
                    "funded-issues",
                    "import-algora-board",
                    "--html",
                    str(html_path),
                    "--org",
                    "exampleorg",
                ]
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("not a server-rendered Algora bounty board", proc.stderr)


if __name__ == "__main__":
    unittest.main()
