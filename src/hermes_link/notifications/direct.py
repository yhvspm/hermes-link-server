"""SQLite-backed DIRECT notification stream, independent of Hermes Link Cloud."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

from .events import IDENTIFIER, validate_event


DEFAULT_RETENTION_SECONDS = 7 * 24 * 60 * 60
DEFAULT_MAX_EVENTS = 10_000


class DirectNotificationStore:
    def __init__(
        self,
        path: Path | str,
        *,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_events: int = DEFAULT_MAX_EVENTS,
    ):
        self.path = Path(path)
        self.retention_seconds = max(60, int(retention_seconds))
        self.max_events = max(1, int(max_events))
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
                self._prune(connection, now=float(event["created_at"]))
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

    def _prune(self, connection: sqlite3.Connection, *, now: float) -> None:
        connection.execute(
            "DELETE FROM direct_events WHERE created_at < ?",
            (now - self.retention_seconds,),
        )
        oldest_retained = connection.execute(
            """
            SELECT sequence FROM direct_events
            ORDER BY sequence DESC
            LIMIT 1 OFFSET ?
            """,
            (self.max_events,),
        ).fetchone()
        if oldest_retained is not None:
            connection.execute(
                "DELETE FROM direct_events WHERE sequence <= ?",
                (int(oldest_retained["sequence"]),),
            )

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

    def read_after_event_id(
        self,
        profile_ids: Iterable[str],
        event_id: str = "",
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return one globally ordered, Profile-scoped event batch.

        Clients persist Event Protocol ``event_id`` values rather than the
        SQLite implementation cursor.  An expired cursor intentionally falls
        back to the retained window; client-side event-id deduplication makes
        that replay safe.
        """

        profiles: list[str] = []
        for value in profile_ids:
            profile_id = str(value or "").strip()
            if not profile_id or profile_id in profiles:
                continue
            if not IDENTIFIER.fullmatch(profile_id):
                raise ValueError("profile_id is invalid")
            profiles.append(profile_id)
        if not profiles:
            raise ValueError("at least one profile_id is required")
        cursor = str(event_id or "").strip()
        if cursor and not IDENTIFIER.fullmatch(cursor):
            raise ValueError("event_id is invalid")
        bounded_limit = max(1, min(int(limit), 500))
        placeholders = ", ".join("?" for _ in profiles)
        with self._lock, closing(self._connect()) as connection:
            sequence = 0
            if cursor:
                row = connection.execute(
                    "SELECT sequence FROM direct_events WHERE event_id = ?",
                    (cursor,),
                ).fetchone()
                if row is not None:
                    sequence = int(row["sequence"])
            rows = connection.execute(
                f"""
                SELECT * FROM direct_events
                WHERE profile_id IN ({placeholders}) AND sequence > ?
                ORDER BY sequence LIMIT ?
                """,
                (*profiles, sequence, bounded_limit),
            ).fetchall()
        return [self._decode(row) for row in rows]
