from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from patchrail import __version__
from patchrail.queue.store import (
    DEFAULT_DB_PATH,
    approve_work_item,
    export_audit_log,
    get_work_item,
    init_queue,
    list_work_items,
    reject_work_item,
)


SCHEMA_VERSION = "patchrail.control_plane.v1"


def _requirements() -> dict[str, Any]:
    return {
        "network_required": False,
        "external_model_required": False,
        "github_token_required": False,
        "github_write_permission_required": False,
        "write_actions_require_human_approval": True,
        "binds_loopback_by_default": True,
    }


def _queue_counts(db_path: Path) -> dict[str, int]:
    counts = {"proposed": 0, "approved": 0, "rejected": 0, "done": 0}
    for item in list_work_items(db_path=db_path):
        counts[str(item["status"])] += 1
    return counts


def _status_payload(db_path: Path) -> dict[str, Any]:
    init_queue(db_path)
    audit_events = export_audit_log(db_path=db_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "patchrail_version": __version__,
        "status": "ok",
        "db_path": str(db_path),
        "queue_counts": _queue_counts(db_path),
        "audit_events": len(audit_events),
        "requirements": _requirements(),
    }


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _work_item_id_and_action(path: str) -> tuple[int, str] | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 3 or parts[0] != "work-items":
        return None
    if parts[2] not in {"approve", "reject"}:
        return None
    return int(parts[1]), parts[2]


def make_handler(db_path: Path = DEFAULT_DB_PATH) -> type[BaseHTTPRequestHandler]:
    resolved_db_path = Path(db_path)

    class PatchRailControlPlaneHandler(BaseHTTPRequestHandler):
        server_version = "PatchRailControlPlane/1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status: HTTPStatus, message: str) -> None:
            self._send_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "error",
                    "error": message,
                    "requirements": _requirements(),
                },
                status=status,
            )

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send_json(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "status": "ok",
                            "requirements": _requirements(),
                        }
                    )
                    return
                if parsed.path == "/status":
                    self._send_json(_status_payload(resolved_db_path))
                    return
                if parsed.path in {"/queue", "/work-items"}:
                    status = parse_qs(parsed.query).get("status", [None])[0]
                    self._send_json(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "items": list_work_items(db_path=resolved_db_path, status=status),
                            "requirements": _requirements(),
                        }
                    )
                    return
                if parsed.path.startswith("/work-items/"):
                    work_item_id = int(parsed.path.removeprefix("/work-items/"))
                    self._send_json(get_work_item(work_item_id, db_path=resolved_db_path))
                    return
                if parsed.path == "/audit-log":
                    self._send_json(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "events": export_audit_log(db_path=resolved_db_path),
                            "requirements": _requirements(),
                        }
                    )
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")
            except (KeyError, ValueError) as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                transition = _work_item_id_and_action(parsed.path)
                if transition is None:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")
                    return
                work_item_id, action = transition
                payload = _read_json_body(self)
                note = payload.get("note")
                if note is not None and not isinstance(note, str):
                    raise ValueError("note must be a string")
                if action == "approve":
                    item = approve_work_item(work_item_id, db_path=resolved_db_path, note=note)
                else:
                    item = reject_work_item(work_item_id, db_path=resolved_db_path, note=note)
                self._send_json(item)
            except json.JSONDecodeError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, f"invalid JSON body: {exc.msg}")
            except ValueError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except KeyError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))

    return PatchRailControlPlaneHandler


def serve_control_plane(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    init_queue(db_path)
    server = ThreadingHTTPServer((host, port), make_handler(db_path))
    try:
        print(
            f"PatchRail control plane listening on http://{host}:{port} with db {db_path}",
            flush=True,
        )
        server.serve_forever()
    finally:
        server.server_close()
