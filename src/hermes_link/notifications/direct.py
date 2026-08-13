"""SQLite-backed DIRECT notification stream, independent of Hermes Link Cloud."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .events import validate_event


class DirectNotificationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS direct_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        event = json.loads(row["payload_json"])
        event["sequence"] = int(row["sequence"])
        return event

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        event = validate_event(payload)
        event.setdefault("created_at", time.time())
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock, closing(self._connect()) as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO direct_events
                        (event_id, dedupe_key, profile_id, event_type, created_at, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        event["dedupe_key"],
                        event["profile_id"],
                        event["event_type"],
                        event["created_at"],
                        encoded,
                    ),
                )
                connection.commit()
                event["sequence"] = int(cursor.lastrowid)
                return event
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM direct_events
                    WHERE event_id = ? OR dedupe_key = ?
                    ORDER BY sequence LIMIT 1
                    """,
                    (event["event_id"], event["dedupe_key"]),
                ).fetchone()
                if row is None:
                    raise
                return self._decode(row)

    def read_after(self, profile_id: str, sequence: int = 0, *, limit: int = 100) -> list[dict[str, Any]]:
        profile = str(profile_id or "").strip()
        if not profile:
            raise ValueError("profile_id is required")
        bounded_limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM direct_events
                WHERE profile_id = ? AND sequence > ?
                ORDER BY sequence LIMIT ?
                """,
                (profile, max(0, int(sequence)), bounded_limit),
            ).fetchall()
        return [self._decode(row) for row in rows]
