"""Activity log: a record of every scan and print, backed by SQLite.

This is the protocol the user asked for: what was scanned/printed, when, to or
from which service, and whether it succeeded. Pure stdlib, no ORM — the schema
is tiny and the queries are trivial.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

Kind = Literal["scan", "print"]
Status = Literal["success", "error", "pending"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,              -- ISO 8601 UTC
    kind        TEXT    NOT NULL,              -- 'scan' | 'print'
    filename    TEXT    NOT NULL,
    service     TEXT,                          -- cloud service key, if any
    status      TEXT    NOT NULL,              -- 'success' | 'error' | 'pending'
    size_bytes  INTEGER,
    detail      TEXT                           -- error message or extra info
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts DESC);
"""


@dataclass
class Activity:
    id: int
    ts: str
    kind: Kind
    filename: str
    service: str | None
    status: Status
    size_bytes: int | None
    detail: str | None


class ActivityLog:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        kind: Kind,
        filename: str,
        *,
        service: str | None = None,
        status: Status = "success",
        size_bytes: int | None = None,
        detail: str | None = None,
    ) -> int:
        """Append one activity row. Returns its id."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO activity (ts, kind, filename, service, status, size_bytes, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, kind, filename, service, status, size_bytes, detail),
            )
            return int(cur.lastrowid)

    def update_status(self, activity_id: int, status: Status, detail: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE activity SET status = ?, detail = ? WHERE id = ?",
                (status, detail, activity_id),
            )

    def set_size(self, activity_id: int, size_bytes: int) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE activity SET size_bytes = ? WHERE id = ?",
                (size_bytes, activity_id),
            )

    def recent(self, limit: int = 100, kind: Kind | None = None) -> list[Activity]:
        q = "SELECT * FROM activity"
        params: list[object] = []
        if kind is not None:
            q += " WHERE kind = ?"
            params.append(kind)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [Activity(**dict(r)) for r in rows]
