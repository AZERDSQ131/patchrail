from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "patchrail.queue.v1"
WORK_ITEM_SCHEMA_VERSION = "patchrail.work_item.v1"
DEFAULT_DB_PATH = Path(".patchrail") / "queue.sqlite"
VALID_STATUSES = {"proposed", "approved", "rejected", "done"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_queue(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    with _connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT,
                rejected_at TEXT,
                decision_note TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_item_id INTEGER,
                action TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        connection.commit()

    return {
        "schema_version": SCHEMA_VERSION,
        "db_path": str(db_path),
        "requirements": _requirements(),
    }


def _requirements() -> dict[str, Any]:
    return {
        "network_required": False,
        "external_model_required": False,
        "github_token_required": False,
        "write_actions_require_human_approval": True,
    }


def _insert_audit_event(
    connection: sqlite3.Connection,
    *,
    work_item_id: int | None,
    action: str,
    note: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_log (work_item_id, action, note, created_at, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (work_item_id, action, note, _now(), json.dumps(payload or {}, sort_keys=True)),
    )


def _row_to_work_item(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["payload_json"]))
    return {
        "schema_version": row["schema_version"],
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "source": row["source"],
        "priority": row["priority"],
        "status": row["status"],
        "payload": payload,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "rejected_at": row["rejected_at"],
        "decision_note": row["decision_note"],
        "requirements": _requirements(),
    }


def add_work_item(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    kind: str,
    title: str,
    source: str | None = None,
    priority: int = 0,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init_queue(db_path)
    timestamp = _now()
    payload_json = json.dumps(payload or {}, sort_keys=True)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO work_items (
                schema_version, kind, title, source, priority, status, payload_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                WORK_ITEM_SCHEMA_VERSION,
                kind,
                title,
                source,
                priority,
                "proposed",
                payload_json,
                timestamp,
                timestamp,
            ),
        )
        work_item_id = int(cursor.lastrowid)
        _insert_audit_event(
            connection,
            work_item_id=work_item_id,
            action="work_item.proposed",
            payload={"kind": kind, "source": source, "priority": priority},
        )
        connection.commit()
    return get_work_item(work_item_id, db_path=db_path)


def list_work_items(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    status: str | None = None,
) -> list[dict[str, Any]]:
    init_queue(db_path)
    with _connect(db_path) as connection:
        if status is None:
            rows = connection.execute(
                "SELECT * FROM work_items ORDER BY priority DESC, id ASC"
            ).fetchall()
        else:
            if status not in VALID_STATUSES:
                raise ValueError(f"unknown queue status: {status}")
            rows = connection.execute(
                "SELECT * FROM work_items WHERE status = ? ORDER BY priority DESC, id ASC",
                (status,),
            ).fetchall()
    return [_row_to_work_item(row) for row in rows]


def get_work_item(work_item_id: int, *, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_queue(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM work_items WHERE id = ?", (work_item_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f"work item not found: {work_item_id}")
    return _row_to_work_item(row)


def _transition_work_item(
    *,
    db_path: Path,
    work_item_id: int,
    status: str,
    audit_action: str,
    note: str | None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown queue status: {status}")
    init_queue(db_path)
    timestamp = _now()
    with _connect(db_path) as connection:
        existing = connection.execute(
            "SELECT status FROM work_items WHERE id = ?", (work_item_id,)
        ).fetchone()
        if existing is None:
            raise KeyError(f"work item not found: {work_item_id}")
        connection.execute(
            """
            UPDATE work_items
            SET status = ?,
                updated_at = ?,
                approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END,
                rejected_at = CASE WHEN ? = 'rejected' THEN ? ELSE rejected_at END,
                decision_note = ?
            WHERE id = ?
            """,
            (status, timestamp, status, timestamp, status, timestamp, note, work_item_id),
        )
        _insert_audit_event(
            connection,
            work_item_id=work_item_id,
            action=audit_action,
            note=note,
            payload={"from_status": existing["status"], "to_status": status},
        )
        connection.commit()
    return get_work_item(work_item_id, db_path=db_path)


def approve_work_item(
    work_item_id: int, *, db_path: Path = DEFAULT_DB_PATH, note: str | None = None
) -> dict[str, Any]:
    return _transition_work_item(
        db_path=db_path,
        work_item_id=work_item_id,
        status="approved",
        audit_action="work_item.approved",
        note=note,
    )


def reject_work_item(
    work_item_id: int, *, db_path: Path = DEFAULT_DB_PATH, note: str | None = None
) -> dict[str, Any]:
    return _transition_work_item(
        db_path=db_path,
        work_item_id=work_item_id,
        status="rejected",
        audit_action="work_item.rejected",
        note=note,
    )


def export_audit_log(*, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_queue(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
    return [
        {
            "schema_version": "patchrail.audit_event.v1",
            "id": row["id"],
            "work_item_id": row["work_item_id"],
            "action": row["action"],
            "note": row["note"],
            "created_at": row["created_at"],
            "payload": json.loads(str(row["payload_json"])),
        }
        for row in rows
    ]
