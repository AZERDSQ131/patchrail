from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from patchrail.queue.server import make_handler
from patchrail.queue.store import add_work_item


class PatchRailQueueServerTests(unittest.TestCase):
    def test_loopback_control_plane_exposes_human_approval_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite"
            item = add_work_item(
                db_path=db_path,
                kind="ci_failure",
                title="Triage dependency install failure",
                source="examples/ci-triage/dependency-failure.log",
                priority=10,
                payload={"failure_class": "python_dependency_resolution"},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            try:
                health = self._request(host, port, "GET", "/health")
                self.assertEqual(health["status"], "ok")
                self.assertFalse(health["requirements"]["network_required"])
                self.assertTrue(health["requirements"]["write_actions_require_human_approval"])

                queue = self._request(host, port, "GET", "/work-items?status=proposed")
                self.assertEqual(len(queue["items"]), 1)
                self.assertEqual(queue["items"][0]["id"], item["id"])
                self.assertEqual(queue["items"][0]["status"], "proposed")

                approved = self._request(
                    host,
                    port,
                    "POST",
                    f"/work-items/{item['id']}/approve",
                    {"note": "Maintainer reviewed evidence"},
                )
                self.assertEqual(approved["status"], "approved")
                self.assertEqual(approved["decision_note"], "Maintainer reviewed evidence")

                status = self._request(host, port, "GET", "/status")
                self.assertEqual(status["queue_counts"]["approved"], 1)
                self.assertEqual(status["queue_counts"]["proposed"], 0)
                self.assertEqual(status["audit_events"], 2)

                audit_log = self._request(host, port, "GET", "/audit-log")
                self.assertEqual(
                    [event["action"] for event in audit_log["events"]],
                    ["work_item.proposed", "work_item.approved"],
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def _request(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            encoded = None
            headers = {}
            if body is not None:
                encoded = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        self.assertEqual(response.status, 200, payload)
        return payload


if __name__ == "__main__":
    unittest.main()
