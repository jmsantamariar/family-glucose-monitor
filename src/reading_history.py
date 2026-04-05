"""Persistent history of periodic glucose readings.

Stores a reading at each polling cycle (typically every ~5 minutes) so that
the dashboard can display a real time-series sparkline instead of synthetic
placeholder data.

The table is kept in a dedicated ``reading_history.db`` file (separate from
``alert_history.db``) to avoid polluting the alert log with routine readings.
Clean-up trims history older than ``max_days`` days (default 3) to avoid
unbounded disk growth.

Public API
----------
* :func:`init_db`         — create table/indexes (idempotent)
* :func:`log_reading`     — persist one glucose reading
* :func:`get_readings`    — retrieve readings for a patient within a time window
* :func:`cleanup_old_readings` — delete readings beyond the retention window
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db import connect_db
from src.models.db_models import ReadingHistory, get_engine

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    patient_name  TEXT NOT NULL,
    glucose_value INTEGER NOT NULL
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_readings_patient_ts ON readings(patient_id, timestamp);",
]

# Per-path engine cache — avoids creating a new engine on every call while
# still supporting multiple DB paths in tests.
_engines: dict[str, object] = {}


def _get_engine(db_path: str):
    """Return (and cache) a SQLAlchemy engine for *db_path*."""
    if db_path not in _engines:
        _engines[db_path] = get_engine(f"sqlite:///{db_path}")
    return _engines[db_path]


def init_db(db_path: str) -> None:
    """Create the readings table and supporting indexes if they do not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect_db(db_path) as conn:
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    logger.debug("Reading history DB initialised at %s", db_path)


def log_reading(
    db_path: str,
    patient_id: str,
    patient_name: str,
    glucose_value: int,
) -> None:
    """Persist a single glucose reading for history tracking."""
    timestamp = datetime.now(timezone.utc).isoformat()
    engine = _get_engine(db_path)
    with Session(engine) as session:
        session.add(
            ReadingHistory(
                timestamp=timestamp,
                patient_id=patient_id,
                patient_name=patient_name,
                glucose_value=int(glucose_value),
            )
        )
        session.commit()
    logger.debug("Reading logged for %s: %d mg/dL", patient_name, glucose_value)


def get_readings(
    db_path: str,
    patient_id: str,
    hours: int = 3,
) -> list[dict]:
    """Return readings for *patient_id* in the last *hours* hours.

    Results are ordered oldest-first so callers can iterate in time order.
    Returns an empty list if the database does not exist yet.
    """
    if not Path(db_path).exists():
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    engine = _get_engine(db_path)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT timestamp, patient_id, patient_name, glucose_value "
                    "FROM readings "
                    "WHERE patient_id = :pid AND timestamp >= :since "
                    "ORDER BY timestamp ASC"
                ),
                {"pid": patient_id, "since": since},
            ).fetchall()
        return [
            {
                "timestamp": row[0],
                "patient_id": row[1],
                "patient_name": row[2],
                "glucose_value": row[3],
            }
            for row in rows
        ]
    except Exception:
        return []


def cleanup_old_readings(db_path: str, max_days: int = 3) -> int:
    """Delete readings older than *max_days* days.

    Returns the number of rows deleted.
    """
    if not Path(db_path).exists():
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
    engine = _get_engine(db_path)

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM readings WHERE timestamp < :cutoff"),
                {"cutoff": cutoff},
            )
            conn.commit()
            deleted = result.rowcount
    except Exception:
        return 0

    if deleted:
        logger.debug("Cleaned up %d old reading(s) from history", deleted)
    return deleted
