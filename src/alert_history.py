"""Persistent alert history using SQLite.

Stores a log of every alert sent so that patterns can be analysed
and visualised in the dashboard without relying on Telegram messages.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    patient_name  TEXT NOT NULL,
    glucose_value INTEGER NOT NULL,
    level         TEXT NOT NULL,
    trend_arrow   TEXT NOT NULL DEFAULT '',
    message       TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_patient_timestamp ON alerts(patient_id, timestamp);",
]


def init_db(db_path: str) -> None:
    """Create the alerts table and supporting indexes if they do not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    logger.debug("Alert history DB initialised at %s", db_path)


def log_alert(
    db_path: str,
    patient_id: str,
    patient_name: str,
    glucose_value: int,
    level: str,
    trend_arrow: str,
    message: str,
) -> None:
    """Record a successfully sent alert in the history database."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alerts
                (timestamp, patient_id, patient_name, glucose_value, level, trend_arrow, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, patient_id, patient_name, int(glucose_value), level, trend_arrow, message),
        )
        conn.commit()
    logger.debug("Alert logged for %s: %s %d mg/dL", patient_name, level, glucose_value)


def get_alerts(
    db_path: str,
    patient_id: str | None = None,
    hours: int = 24,
) -> list[dict]:
    """Return alerts from the last *hours* hours, optionally filtered by patient.

    Returns an empty list if the database does not exist yet.
    """
    if not Path(db_path).exists():
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if patient_id is not None:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE timestamp >= ? AND patient_id = ? ORDER BY timestamp DESC",
                    (since, patient_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE timestamp >= ? ORDER BY timestamp DESC",
                    (since,),
                ).fetchall()
    except sqlite3.OperationalError:
        # Table may not exist in an empty DB file
        return []

    return [dict(row) for row in rows]


def cleanup_old_alerts(db_path: str, max_days: int = 7) -> int:
    """Delete alerts older than *max_days* days.

    Returns the number of rows deleted.
    """
    if not Path(db_path).exists():
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff,))
            conn.commit()
            deleted = cursor.rowcount
    except sqlite3.OperationalError:
        return 0

    if deleted:
        logger.debug("Cleaned up %d old alert(s) from history", deleted)
    return deleted
