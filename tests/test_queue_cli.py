from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PatchRailQueueTests(unittest.TestCase):
    def test_queue_lifecycle_keeps_write_actions_human_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite"

            init = subprocess.run(
                [sys.executable, "-m", "patchrail", "queue", "init", "--db", str(db_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertTrue(db_path.exists())
            init_payload = json.loads(init.stdout)
            self.assertEqual(init_payload["schema_version"], "patchrail.queue.v1")
            self.assertFalse(init_payload["requirements"]["network_required"])

            added = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "queue",
                    "add",
                    "--db",
                    str(db_path),
                    "--kind",
                    "ci_failure",
                    "--title",
                    "Triage failed dependency install",
                    "--source",
                    "examples/ci-triage/dependency-failure.log",
                    "--priority",
                    "10",
                    "--payload-json",
                    '{"failure_class":"python_dependency_resolution"}',
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            item = json.loads(added.stdout)
            self.assertEqual(item["schema_version"], "patchrail.work_item.v1")
            self.assertEqual(item["status"], "proposed")
            self.assertEqual(item["payload"]["failure_class"], "python_dependency_resolution")
            self.assertTrue(item["requirements"]["write_actions_require_human_approval"])

            approved = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "queue",
                    "approve",
                    "--db",
                    str(db_path),
                    str(item["id"]),
                    "--note",
                    "Maintainer reviewed evidence",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)
            approved_item = json.loads(approved.stdout)
            self.assertEqual(approved_item["status"], "approved")
            self.assertEqual(approved_item["decision_note"], "Maintainer reviewed evidence")
            self.assertIsNotNone(approved_item["approved_at"])

            listed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "queue",
                    "list",
                    "--db",
                    str(db_path),
                    "--status",
                    "approved",
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            approved_items = json.loads(listed.stdout)
            self.assertEqual(len(approved_items), 1)
            self.assertEqual(approved_items[0]["id"], item["id"])

            exported = subprocess.run(
                [sys.executable, "-m", "patchrail", "queue", "export", "--db", str(db_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            events = [json.loads(line) for line in exported.stdout.splitlines()]
            self.assertEqual(
                [event["action"] for event in events],
                ["work_item.proposed", "work_item.approved"],
            )

    def test_schema_command_emits_work_item_contract(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "schema", "work-item"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        schema = json.loads(proc.stdout)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "patchrail.work_item.v1")
        self.assertEqual(
            schema["properties"]["requirements"]["properties"][
                "write_actions_require_human_approval"
            ]["const"],
            True,
        )

    def test_queue_from_ci_result_creates_proposed_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite"
            result_path = Path(tmpdir) / "ci-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_result.v1",
                        "failure_class": "python_dependency_resolution",
                        "confidence": 0.95,
                        "requirements": {
                            "billing_required": False,
                            "external_model_required": False,
                            "network_required": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "queue",
                    "from-ci-result",
                    "--db",
                    str(db_path),
                    "--result",
                    str(result_path),
                    "--source",
                    "examples/ci-triage/dependency-failure.log",
                    "--priority",
                    "20",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            item = json.loads(proc.stdout)
            self.assertEqual(item["kind"], "ci_failure")
            self.assertEqual(item["status"], "proposed")
            self.assertEqual(item["priority"], 20)
            self.assertEqual(item["source"], "examples/ci-triage/dependency-failure.log")
            self.assertEqual(item["title"], "Review CI failure: python_dependency_resolution")
            self.assertEqual(item["payload"]["failure_class"], "python_dependency_resolution")
            self.assertEqual(
                item["payload"]["ci_result"]["requirements"]["network_required"], False
            )
            self.assertTrue(item["requirements"]["write_actions_require_human_approval"])


if __name__ == "__main__":
    unittest.main()
