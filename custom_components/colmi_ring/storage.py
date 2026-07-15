from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Any


@dataclass
class SyncSummary:
    address: str
    synced_at: datetime
    start: datetime
    end: datetime
    heart_rate_rows: int
    sport_detail_rows: int


class RingDataStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS rings (
                    ring_id INTEGER PRIMARY KEY,
                    address TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS syncs (
                    sync_id INTEGER PRIMARY KEY,
                    comment TEXT,
                    ring_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    start_timestamp TEXT NOT NULL,
                    end_timestamp TEXT NOT NULL,
                    FOREIGN KEY (ring_id) REFERENCES rings (ring_id)
                );

                CREATE TABLE IF NOT EXISTS heart_rates (
                    heart_rate_id INTEGER PRIMARY KEY,
                    reading INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    ring_id INTEGER NOT NULL,
                    sync_id INTEGER NOT NULL,
                    UNIQUE (ring_id, timestamp),
                    FOREIGN KEY (ring_id) REFERENCES rings (ring_id),
                    FOREIGN KEY (sync_id) REFERENCES syncs (sync_id)
                );

                CREATE TABLE IF NOT EXISTS sport_details (
                    sport_detail_id INTEGER PRIMARY KEY,
                    calories INTEGER NOT NULL,
                    steps INTEGER NOT NULL,
                    distance INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    ring_id INTEGER NOT NULL,
                    sync_id INTEGER NOT NULL,
                    UNIQUE (ring_id, timestamp),
                    FOREIGN KEY (ring_id) REFERENCES rings (ring_id),
                    FOREIGN KEY (sync_id) REFERENCES syncs (sync_id)
                );
                """
            )

    def _ensure_ring(self, conn: sqlite3.Connection, address: str) -> int:
        conn.execute("INSERT OR IGNORE INTO rings(address) VALUES (?)", (address,))
        row = conn.execute("SELECT ring_id FROM rings WHERE address = ?", (address,)).fetchone()
        assert row is not None
        return int(row["ring_id"])

    def get_last_sync(self, address: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.end_timestamp
                FROM syncs s
                JOIN rings r ON r.ring_id = s.ring_id
                WHERE r.address = ?
                ORDER BY s.end_timestamp DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row["end_timestamp"]))

    def write_sync(
        self,
        *,
        address: str,
        start: datetime,
        end: datetime,
        heart_rate_rows: list[dict[str, Any]],
        sport_detail_rows: list[dict[str, Any]],
    ) -> SyncSummary:
        synced_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            ring_id = self._ensure_ring(conn, address)
            cursor = conn.execute(
                """
                INSERT INTO syncs(comment, ring_id, timestamp, start_timestamp, end_timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Home Assistant sync",
                    ring_id,
                    synced_at.isoformat(),
                    start.isoformat(),
                    end.isoformat(),
                ),
            )
            sync_id = int(cursor.lastrowid)

            conn.executemany(
                """
                INSERT OR REPLACE INTO heart_rates(reading, timestamp, ring_id, sync_id)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (row["reading"], row["timestamp"], ring_id, sync_id)
                    for row in heart_rate_rows
                ],
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO sport_details(calories, steps, distance, timestamp, ring_id, sync_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["calories"],
                        row["steps"],
                        row["distance"],
                        row["timestamp"],
                        ring_id,
                        sync_id,
                    )
                    for row in sport_detail_rows
                ],
            )
            conn.commit()

        return SyncSummary(
            address=address,
            synced_at=synced_at,
            start=start,
            end=end,
            heart_rate_rows=len(heart_rate_rows),
            sport_detail_rows=len(sport_detail_rows),
        )

    def get_recent_metrics(self, address: str) -> dict[str, Any]:
        with self._connect() as conn:
            latest_hr = conn.execute(
                """
                SELECT reading, timestamp
                FROM heart_rates hr
                JOIN rings r ON r.ring_id = hr.ring_id
                WHERE r.address = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            latest_steps = conn.execute(
                """
                SELECT steps, calories, distance, timestamp
                FROM sport_details sd
                JOIN rings r ON r.ring_id = sd.ring_id
                WHERE r.address = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            latest_sync = conn.execute(
                """
                SELECT timestamp, start_timestamp, end_timestamp
                FROM syncs s
                JOIN rings r ON r.ring_id = s.ring_id
                WHERE r.address = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()

        result: dict[str, Any] = {}
        if latest_hr is not None:
            result["heart_rate"] = int(latest_hr["reading"])
            result["heart_rate_timestamp"] = str(latest_hr["timestamp"])
        if latest_steps is not None:
            result["steps"] = int(latest_steps["steps"])
            result["calories"] = int(latest_steps["calories"])
            result["distance"] = int(latest_steps["distance"])
            result["steps_timestamp"] = str(latest_steps["timestamp"])
        if latest_sync is not None:
            result["last_sync"] = str(latest_sync["timestamp"])
            result["last_sync_start"] = str(latest_sync["start_timestamp"])
            result["last_sync_end"] = str(latest_sync["end_timestamp"])
        return result

    @staticmethod
    def summary_as_dict(summary: SyncSummary) -> dict[str, Any]:
        data = asdict(summary)
        data["synced_at"] = summary.synced_at.isoformat()
        data["start"] = summary.start.isoformat()
        data["end"] = summary.end.isoformat()
        return data