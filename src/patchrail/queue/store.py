from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "patchrail.queue.v1"
DEFAULT_QUEUE_PATH = Path(".patchrail") / "queue.sqlite"

VALID_APPROVAL_STATES = {"pending", "approved", "rejected"}


@dataclass(frozen=True)
class QueueItem:
    id: str
    kind: str
    title: str
    source: str
    status: str
    approval_state: str
    write_actions_allowed: bool
    created_at: str
    updated_at: str
    payload: dict[str, Any]
    decision_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "source": self.source,
            "status": self.status,
            "approval_state": self.approval_state,
            "write_actions_allowed": self.write_actions_allowed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "payload": self.payload,
            "decision_note": self.decision_note,
        }


def _now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_queue(db_path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_items (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              source TEXT NOT NULL,
              status TEXT NOT NULL,
              approval_state TEXT NOT NULL,
              write_actions_allowed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              decision_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL,
              event_type TEXT NOT NULL,
              work_item_id TEXT,
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (SCHEMA_VERSION,),
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "db_path": str(db_path),
        "local_first": True,
        "write_actions_allowed_by_default": False,
    }


def _row_to_item(row: sqlite3.Row) -> QueueItem:
    return QueueItem(
        id=str(row["id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        source=str(row["source"]),
        status=str(row["status"]),
        approval_state=str(row["approval_state"]),
        write_actions_allowed=bool(row["write_actions_allowed"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        payload=json.loads(str(row["payload_json"])),
        decision_note=row["decision_note"],
    )


def _write_audit_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    work_item_id: str | None,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events(ts, event_type, work_item_id, payload_json)
        VALUES(?, ?, ?, ?)
        """,
        (_now(), event_type, work_item_id, json.dumps(payload, sort_keys=True)),
    )


def add_work_item(
    *,
    db_path: Path = DEFAULT_QUEUE_PATH,
    kind: str,
    title: str,
    source: str = "manual",
    payload: dict[str, Any] | None = None,
) -> QueueItem:
    init_queue(db_path)
    item_id = f"prq_{uuid4().hex[:12]}"
    ts = _now()
    safe_payload = payload or {}
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO work_items(
              id, kind, title, source, status, approval_state,
              write_actions_allowed, created_at, updated_at, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                kind,
                title,
                source,
                "open",
                "pending",
                0,
                ts,
                ts,
                json.dumps(safe_payload, sort_keys=True),
            ),
        )
        _write_audit_event(
            conn,
            event_type="work_item_added",
            work_item_id=item_id,
            payload={"kind": kind, "source": source, "approval_state": "pending"},
        )
    return show_work_item(db_path=db_path, item_id=item_id)


def list_work_items(
    *,
    db_path: Path = DEFAULT_QUEUE_PATH,
    status: str | None = None,
    approval_state: str | None = None,
) -> list[QueueItem]:
    init_queue(db_path)
    clauses: list[str] = []
    values: list[str] = []
    if status:
        clauses.append("status = ?")
        values.append(status)
    if approval_state:
        if approval_state not in VALID_APPROVAL_STATES:
            raise ValueError(f"unknown approval state: {approval_state}")
        clauses.append("approval_state = ?")
        values.append(approval_state)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM work_items {where} ORDER BY created_at DESC, id DESC",
            values,
        ).fetchall()
    return [_row_to_item(row) for row in rows]


def show_work_item(*, db_path: Path = DEFAULT_QUEUE_PATH, item_id: str) -> QueueItem:
    init_queue(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    return _row_to_item(row)


def _set_approval_state(
    *,
    db_path: Path,
    item_id: str,
    approval_state: str,
    decision_note: str | None,
) -> QueueItem:
    if approval_state not in VALID_APPROVAL_STATES:
        raise ValueError(f"unknown approval state: {approval_state}")
    init_queue(db_path)
    ts = _now()
    status = "open" if approval_state == "approved" else approval_state
    with _connect(db_path) as conn:
        current = conn.execute("SELECT id FROM work_items WHERE id = ?", (item_id,)).fetchone()
        if current is None:
            raise KeyError(item_id)
        conn.execute(
            """
            UPDATE work_items
            SET approval_state = ?, status = ?, decision_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (approval_state, status, decision_note, ts, item_id),
        )
        _write_audit_event(
            conn,
            event_type=f"work_item_{approval_state}",
            work_item_id=item_id,
            payload={"decision_note": decision_note},
        )
    return show_work_item(db_path=db_path, item_id=item_id)


def approve_work_item(
    *,
    db_path: Path = DEFAULT_QUEUE_PATH,
    item_id: str,
    decision_note: str | None = None,
) -> QueueItem:
    return _set_approval_state(
        db_path=db_path,
        item_id=item_id,
        approval_state="approved",
        decision_note=decision_note,
    )


def reject_work_item(
    *,
    db_path: Path = DEFAULT_QUEUE_PATH,
    item_id: str,
    decision_note: str | None = None,
) -> QueueItem:
    return _set_approval_state(
        db_path=db_path,
        item_id=item_id,
        approval_state="rejected",
        decision_note=decision_note,
    )


def export_work_items(*, db_path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "db_path": str(db_path),
        "local_first": True,
        "work_items": [item.to_dict() for item in list_work_items(db_path=db_path)],
    }
