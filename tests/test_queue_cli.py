from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def run_patchrail(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        text=True,
        capture_output=True,
        check=False,
    )


class PatchRailQueueTests(unittest.TestCase):
    def test_queue_flow_keeps_work_items_local_and_human_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "queue.sqlite"

            init_proc = run_patchrail(["queue", "--db", str(db), "init"])
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            init_payload = json.loads(init_proc.stdout)
            self.assertEqual(init_payload["schema_version"], "patchrail.queue.v1")
            self.assertEqual(init_payload["write_actions_allowed_by_default"], False)

            add_proc = run_patchrail(
                [
                    "queue",
                    "--db",
                    str(db),
                    "add",
                    "--kind",
                    "ci_failure",
                    "--title",
                    "Investigate failing dependency install",
                    "--source",
                    "local-fixture",
                    "--payload-json",
                    '{"report": "patchrail-ci-report.md"}',
                ]
            )
            self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
            added = json.loads(add_proc.stdout)
            self.assertEqual(added["approval_state"], "pending")
            self.assertEqual(added["write_actions_allowed"], False)
            self.assertEqual(added["payload"]["report"], "patchrail-ci-report.md")

            list_proc = run_patchrail(
                [
                    "queue",
                    "--db",
                    str(db),
                    "list",
                    "--approval-state",
                    "pending",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
            listed = json.loads(list_proc.stdout)
            self.assertEqual(len(listed["work_items"]), 1)
            self.assertEqual(listed["work_items"][0]["id"], added["id"])

            approve_proc = run_patchrail(
                [
                    "queue",
                    "--db",
                    str(db),
                    "approve",
                    added["id"],
                    "--note",
                    "Maintainer reviewed the local report.",
                ]
            )
            self.assertEqual(approve_proc.returncode, 0, approve_proc.stderr)
            approved = json.loads(approve_proc.stdout)
            self.assertEqual(approved["approval_state"], "approved")
            self.assertEqual(approved["status"], "open")
            self.assertEqual(approved["write_actions_allowed"], False)

            export_proc = run_patchrail(["queue", "--db", str(db), "export", "--format", "jsonl"])
            self.assertEqual(export_proc.returncode, 0, export_proc.stderr)
            exported = [json.loads(line) for line in export_proc.stdout.splitlines()]
            self.assertEqual(exported[0]["id"], added["id"])

    def test_queue_reject_marks_item_closed_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "queue.sqlite"
            add_proc = run_patchrail(
                [
                    "queue",
                    "--db",
                    str(db),
                    "add",
                    "--kind",
                    "release_prep",
                    "--title",
                    "Prepare release checklist",
                ]
            )
            self.assertEqual(add_proc.returncode, 0, add_proc.stderr)
            item_id = json.loads(add_proc.stdout)["id"]

            reject_proc = run_patchrail(
                ["queue", "--db", str(db), "reject", item_id, "--note", "Needs more evidence."]
            )

            self.assertEqual(reject_proc.returncode, 0, reject_proc.stderr)
            rejected = json.loads(reject_proc.stdout)
            self.assertEqual(rejected["approval_state"], "rejected")
            self.assertEqual(rejected["status"], "rejected")
            self.assertIn("Needs more evidence", rejected["decision_note"])

    def test_queue_show_unknown_item_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "queue.sqlite"
            proc = run_patchrail(["queue", "--db", str(db), "show", "prq_missing"])

            self.assertEqual(proc.returncode, 1)
            self.assertIn("Unknown work item", proc.stderr)


if __name__ == "__main__":
    unittest.main()
